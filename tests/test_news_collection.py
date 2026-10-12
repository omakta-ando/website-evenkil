import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import telegram_news as n
import news_sources as d

NOW = dt.datetime(2026, 10, 11, 12, tzinfo=n.TZ)

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(n, 'now_local', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        n.AUDIT = d.Audit()

    def test_dates(self):
        for value in ['Sun, 11 Oct 2026 08:00:00 GMT', '2026-10-11T08:00:00Z', '11 октября 2026', '11.10.2026 12:00']:
            self.assertEqual(n.parse_date(value).date(), NOW.date())
        for value in ['', '31.02.2026', 'not a date']:
            self.assertIsNone(n.parse_date(value))

    def test_entity_context_and_noise(self):
        self.assertEqual(n.story_relevance({'title':'В Иенгре открыли новую школу'}), 'context')
        self.assertEqual(n.story_relevance({'title':'Фестиваль культуры в Хатыстыре'}), 'context')
        self.assertEqual(n.story_relevance({'title':'Фестиваль культуры: Хатыстыр'}), 'context')
        self.assertIsNone(n.story_relevance({'title':'Погода в Иенгре'}))
        self.assertEqual(n.story_relevance({'title':'«Эвенкийская жизнь» получила спецприз на медиафоруме «Енисей»'}), 'context')
        self.assertEqual(n.story_relevance({'title':'Как обстоят дела с продуктами в Ессее?'}), 'context')
        self.assertIsNone(n.story_relevance({'title':'Новая школа в Москве'}))
        self.assertTrue(n.is_excluded_story({'title':'Эвенки — участники СВО'}))

    def test_story_region_uses_explicit_place_and_keeps_national_topics_general(self):
        self.assertEqual(n.story_region({'title':'Власти Красноярского края ускорили доставку продуктов в Эвенкию'}, 'Общие новости'), 'Красноярский край')
        self.assertEqual(n.story_region({'title':'Копии петроглифов появились в ЕАО','source':'EAOMedia'}, 'Общие новости'), 'Еврейская автономная область')
        self.assertEqual(n.story_region({'title':'Якутия в фокусе: северный завоз','source':'YakutiaMedia'}, 'Общие новости'), 'Якутия')
        self.assertEqual(n.story_region({'title':'Северный завоз успешно завершается в 19 регионах'}, 'Общие новости'), 'Общие новости')
        self.assertEqual(n.story_region({'title':'Северный завоз успешно завершается в 19 регионах','source':'YakutiaMedia'}, 'Общие новости'), 'Общие новости')
        self.assertEqual(n.story_region({'title':'Песня на эвенкийском языке','source':'YouTube'}, 'Общие новости'), 'Общие новости')
        self.assertEqual(n.story_region({'title':'鄂温克族驯鹿文化'}, 'Общие новости'), 'Зарубежные источники')
        self.assertEqual(n.story_region({'url':'https://ilken.ru/2026/10/11/sahamin-afanasev-i-elena-golomareva-obsudili-itogovyj-dokument-ii-foruma-zhenshhin-severa','title':'Участники обсудили итоги форума'}, 'Общие новости'), 'Якутия')

    def test_idn_and_non_ascii_request_and_secret_redaction(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'ok'
        with patch.object(n.urllib.request,'urlopen',return_value=response) as call:
            self.assertEqual(n.request('https://таймыр.рф/новости/'),b'ok')
        request=call.call_args.args[0]
        self.assertIn('xn--',request.full_url)
        self.assertNotIn('новости',request.full_url)
        with patch.object(n.urllib.request,'urlopen',return_value=response):
            n.request('https://api.telegram.org/botsecret/sendMessage',data=b'secret')
        self.assertNotIn('secret',json.dumps(n.AUDIT.rows))

    def test_international_query_names_pass_filter(self):
        for name in ['Oroqen','Oroqin','Khamnigan','Evenki','鄂温克','에벤키']:
            self.assertEqual(n.story_relevance({'title':name+' culture'}),'direct')

    def test_canonical(self):
        self.assertEqual(d.canonical_url('https://EXAMPLE.org/a/?utm_source=x&id=2#part'), 'https://example.org/a?id=2')
        self.assertNotEqual(d.canonical_url('https://example.org/a?id=2'), d.canonical_url('https://example.org/a?id=3'))

    def test_all_configured_publishers_are_directly_requested(self):
        domains=n.load_source_domains()
        with patch.object(n,'request',side_effect=OSError('offline')) as req:
            self.assertEqual(d.fetch_domains(n,domains,json.loads(n.SOURCES_FILE.read_text()),n.AUDIT),[])
        self.assertEqual(req.call_count,len(domains))
        self.assertEqual(set(n.AUDIT.rows),set(domains))
        self.assertTrue(all(row['counts'].get('completed') == 1 for row in n.AUDIT.rows.values()))

    def test_legacy_encoding_and_www_article_links(self):
        home='<meta charset="windows-1251"><a href="https://www.example.org/a">Эвенки открыли новый музей культуры</a>'.encode('cp1251')
        article=('<meta property="og:title" content="Эвенки открыли музей"><meta property="article:published_time" content="2026-10-11">').encode()
        self.assertIn('Эвенки',d.decode_html(home))
        with patch.object(n,'request',side_effect=[home,article]):
            self.assertEqual(len(d.fetch_domains(n,['example.org'],{},n.AUDIT)),1)

    def test_broken_rss_still_uses_html(self):
        home=b'<link rel="alternate" type="application/rss+xml" href="/feed"><a href="/a">A sufficiently long article title</a>'
        article='<meta property="og:title" content="Эвенки открыли музей"><meta property="article:published_time" content="2026-10-11">'.encode()
        with patch.object(n,'request',side_effect=[home,b'not xml',article]):
            self.assertEqual(len(d.fetch_domains(n,['example.org'],{},n.AUDIT)),1)
        self.assertEqual(n.AUDIT.rows['example.org']['counts']['invalid_feed'],1)

    def test_full_summary_relevance_survives_short_excerpt(self):
        rss=('<rss><channel><item><title>Новое событие</title><link>https://example.org/a</link><pubDate>2026-10-11</pubDate><description>'+('Подробности ' * 70)+'Эвенки открыли музей</description></item></channel></rss>').encode()
        with patch.object(n,'request',return_value=rss):
            result=d.fetch_domains(n,['example.org'],{},n.AUDIT)
        self.assertEqual(len(result),1)
        self.assertLessEqual(len(result[0]['description']),420)
        self.assertTrue(n.is_evenki_related(result[0]))

    def test_atom_and_namespaced_rss(self):
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Title</title><link href="https://x/a"/><published>2026-10-11</published><summary>Text</summary></entry></feed>'
        self.assertEqual(list(d.rss_items(atom))[0]['url'], 'https://x/a')
        rss = b'<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title>Title</title><link>https://x/a</link><dc:date>2026-10-11</dc:date></item></channel></rss>'
        self.assertEqual(list(d.rss_items(rss))[0]['date'], '2026-10-11')

    def test_direct_feed_discovery_and_reasons(self):
        page = b'<link rel="alternate" type="application/rss+xml" href="/rss">'
        def item(title, path, date):
            return f'<item><title>{title}</title><link>https://example.org/{path}</link><pubDate>{date}</pubDate></item>'
        rss = ('<rss><channel>' + item('Эвенки открыли музей','a','2026-10-11') + item('Погода','b','2026-10-11') + item('Эвенки','c','bad') + item('Эвенки','d','2026-11-11') + item('Эвенки','e','2026-01-01') + '</channel></rss>').encode()
        with patch.object(n,'request',side_effect=lambda url,**kwargs: page if url.endswith('/') else rss):
            result = d.fetch_domains(n,['example.org'],{},n.AUDIT)
        self.assertEqual(len(result),1)
        counts = n.AUDIT.rows['example.org']['counts']
        for reason in ['accepted','irrelevant','invalid_date','future_date','outside_window']:
            self.assertEqual(counts[reason],1)

    def test_html_jsonld_fallback(self):
        home = b'<a href="/article">A sufficiently long article headline</a>'
        article = ('<script type="application/ld+json">' + json.dumps({'@graph':[{'@type':'NewsArticle','headline':'Эвенки открыли музей','datePublished':'2026-10-11','url':'/article','description':'Культура'}]}) + '</script>').encode()
        with patch.object(n,'request',side_effect=lambda url,**kwargs:home if url.endswith('/') else article):
            result = d.fetch_domains(n,['example.org'],{},n.AUDIT)
        self.assertEqual(result[0]['url'],'https://example.org/article')

    def test_bad_charset_does_not_abort_other_sources(self):
        def request(url,**kwargs):
            if 'bad.org' in url:
                return b'<meta charset="text">'
            return b'<div id="root"></div>'
        with patch.object(n,'request',side_effect=request):
            self.assertEqual(d.fetch_domains(n,['bad.org','good.org'],{},n.AUDIT),[])
        self.assertIn('invalid_encoding_fallback',n.AUDIT.rows['bad.org']['counts'])
        self.assertIn('completed',n.AUDIT.rows['bad.org']['counts'])
        self.assertIn('completed',n.AUDIT.rows['good.org']['counts'])

    def test_all_domains_recorded_even_failure_or_js(self):
        def request(url, **kwargs):
            if 'bad.org' in url:
                raise urllib.error.HTTPError(url,403,'Forbidden',{},None)
            return b'<div id="root"></div><script src="app.js"></script>'
        with patch.object(n,'request',side_effect=request):
            result = d.fetch_domains(n,['bad.org','js.org'],{},n.AUDIT)
        self.assertEqual(result,[])
        self.assertIn('request_failed', n.AUDIT.rows['bad.org']['counts'])
        self.assertIn('unsupported_html_or_js', n.AUDIT.rows['js.org']['counts'])

    def test_page_limit_visible(self):
        home = ''.join(f'<a href="/{i}">A sufficiently long headline {i}</a>' for i in range(4)).encode()
        with patch.object(n,'request',return_value=home):
            d.fetch_domains(n,['example.org'],{'directDiscovery':{'maxArticlePages':1}},n.AUDIT)
        self.assertEqual(n.AUDIT.rows['example.org']['counts']['article_page_limit'],1)

    def test_telegram_pagination_nested_text(self):
        def page(number, date, text):
            return f'<div class="tgme_widget_message_wrap"><div data-post="test/{number}"><div class="tgme_widget_message_text">{text}<div> продолжение </div> текста</div><time datetime="{date}"></time></div></div>'.encode()
        accounts = {'socialAccounts':[{'id':'test','url':'https://t.me/test','label':'Test'}]}
        with patch.object(Path,'read_text',return_value=json.dumps(accounts)), patch.object(n,'request',side_effect=[page(20,'2026-10-11T08:00:00Z','Эвенки'),page(10,'2026-10-10T08:00:00Z','Эвенки'),page(1,'2026-10-01T08:00:00Z','Эвенки')]) as req:
            result=n.fetch_telegram_public_channels()
        self.assertEqual(len(result),2)
        self.assertIn('?before=20', req.call_args_list[1].args[0])
        self.assertIn('продолжение текста',result[0]['description'])

    def test_vk_missing_token_each_account(self):
        data={'socialAccounts':[{'id':'vk1','url':'https://vk.com/test'},{'id':'vk2','url':'https://vk.ru/test2'}]}
        with patch.dict(os.environ,{'VK_ACCESS_TOKEN':''}),patch.object(Path,'read_text',return_value=json.dumps(data)):
            self.assertEqual(n.fetch_vk_public_walls(),[])
        self.assertEqual(n.AUDIT.rows['vk1']['counts']['missing_vk_token'],1)
        self.assertEqual(n.AUDIT.rows['vk2']['counts']['missing_vk_token'],1)

    def test_vk_pinned_and_numeric_owner(self):
        accounts={'socialAccounts':[{'id':'vk1','url':'https://vk.com/public123','label':'VK'}]}
        recent={'date':int(NOW.timestamp()),'owner_id':-123,'id':1,'text':'Эвенки открыли музей'}
        old={'date':int((NOW-dt.timedelta(days=20)).timestamp()),'owner_id':-123,'id':2,'text':'Эвенки','is_pinned':1}
        batch=[old]+[dict(recent,id=i) for i in range(1,100)]
        with patch.dict(os.environ,{'VK_ACCESS_TOKEN':'secret'}),patch.object(Path,'read_text',return_value=json.dumps(accounts)),patch.object(n,'request',side_effect=[json.dumps({'response':{'items':batch}}).encode(),json.dumps({'response':{'items':[]}}).encode()]) as req,patch.object(n.time,'sleep'):
            result=n.fetch_vk_public_walls()
        self.assertEqual(len(result),99)
        params=n.urllib.parse.parse_qs(req.call_args_list[0].kwargs['data'].decode())
        self.assertEqual(params['owner_id'],['-123'])
        self.assertEqual(n.urllib.parse.parse_qs(req.call_args_list[1].kwargs['data'].decode())['offset'],['100'])

    def test_arun_without_ethnonym_survives_site_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'news-data.js').write_text('window.newsStories=[];')
            state=root/'state.json'
            item={'id':'a','url':'https://arun-rb.ru/a','title':'Открытие выставки','description':'Творческие встречи','arunNews':'1','siteEligible':'1','source':'Арун','day':'2026-10-11','published':NOW.isoformat(),'region':'Бурятия'}
            with patch.object(n,'ROOT',root),patch.object(n,'STATE_FILE',state):
                self.assertEqual(n.update_site_news_feed([item]),1)
                self.assertEqual(n.update_site_news_feed([item]),0)
                self.assertEqual(n.load_site_news_stories()[0]['region'],'Бурятия')
                n.save_state({'version':1,'seen':{},'daily':{},'pendingTelegram':[item]})
                self.assertEqual(len(n.read_state()['pendingTelegram']),1)

    def test_previously_added_news_fixture_keeps_full_text_decision(self):
        fixtures=json.loads((Path(__file__).parent/'fixtures'/'missed-news.json').read_text())
        for item in fixtures:
            relevance=n.story_relevance(item)
            self.assertEqual(relevance,item['expectedRelevance'])
            short=dict(item,description=item['description'][:420],detectedRelevance=relevance)
            self.assertTrue(n.is_evenki_related(short))

    def test_full_collect_keeps_trusted_category_and_queues_without_sending(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original={'title':'Старая публикация','link':'https://old.org/a','region':'Якутия','date':'2026-10-01','source':'Old'}
            (root/'news-data.js').write_text('window.newsStories='+json.dumps([original])+';')
            item={'id':'arun-id','url':'https://arun-rb.ru/exhibit','title':'Открытие выставки','description':'Новая выставка','arunNews':'1','source':'Арун','day':'2026-10-11','published':NOW.isoformat()}
            with patch.object(n,'ROOT',root), patch.object(n,'STATE_FILE',root/'state.json'), patch.object(n,'AUDIT_FILE',root/'audit.json'), patch.object(sys,'argv',['collector']), patch.object(n,'fetch_items',return_value=[item]), patch.object(n,'telegram_send') as send:
                self.assertEqual(n.main(),0)
                stories=n.load_site_news_stories()
                self.assertIn(original,stories)
                self.assertEqual(len(stories),2)
                self.assertEqual(len(n.read_state()['pendingTelegram']),1)
                send.assert_not_called()

    def test_queries_keep_geographic_qualifier_unquoted(self):
        self.assertEqual(n.quote_search_term('Хатыстыр культура'), 'Хатыстыр культура')
        self.assertEqual(n.quote_search_term('"эвенкийский язык" школа'), '"эвенкийский язык" школа')

    def test_json_data_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            story={'title':'Старая новость','link':'https://x/a','image':{'x':True}}
            (root/'news-data.js').write_text('window.newsStories='+json.dumps([story])+';')
            with patch.object(n,'ROOT',root):
                self.assertEqual(n.load_site_news_stories(),[story])

    def test_audit_only_does_not_publish(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(sys,'argv',['collector','--audit-only']),patch.object(n,'AUDIT_FILE',Path(temp)/'audit.json'),patch.object(n,'fetch_items',return_value=[]),patch.object(n,'read_state',return_value={}),patch.object(n,'save_state') as state,patch.object(n,'update_site_news_feed') as site,patch.object(n,'telegram_send') as send:
            self.assertEqual(n.main(),0)
            state.assert_not_called(); site.assert_not_called(); send.assert_not_called()

if __name__=='__main__':
    unittest.main()
