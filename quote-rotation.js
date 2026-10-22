(()=>{
  const target=document.getElementById('siteQuoteText');
  if(!target)return;
  const sourceNode=document.getElementById('siteQuoteSource');
  const band=target.closest('.quote-band')||target;
  const defaults=window.TAEZHNAYA_QUOTES||[];
  const savedKey='taezhnaya-nit-quotes-v3';
  const lastKey='taezhnaya-nit-shared-last-quote-v1';
  let quotes=defaults;
  try{const saved=JSON.parse(localStorage.getItem(savedKey));if(Array.isArray(saved)&&saved.length)quotes=saved.filter(q=>q&&typeof q.text==='string'&&q.text.trim())}catch(e){}
  if(!quotes.length)return;
  let index=-1;
  let pendingUpdate=null;
  let rotationTimer=null;
  try{const previous=Number(localStorage.getItem(lastKey));if(Number.isInteger(previous)&&previous>=0&&previous<quotes.length)index=previous}catch(e){}
  band.tabIndex=0;
  band.setAttribute('aria-label','Цитата. Нажмите, чтобы показать следующую.');
  band.style.cursor='pointer';
  band.addEventListener('focus',()=>{band.style.outline='2px solid var(--gold,#d8b276)';band.style.outlineOffset='5px'});
  band.addEventListener('blur',()=>{band.style.outline='';band.style.outlineOffset=''});
  const show=(animate=false)=>{
    if(pendingUpdate){window.clearTimeout(pendingUpdate);pendingUpdate=null}
    if(animate)target.classList.add('is-changing');
    const update=()=>{
      index=(index+1)%quotes.length;
      const quote=quotes[index];
      target.textContent=quote.text;
      if(sourceNode){
        sourceNode.replaceChildren();
        const label=String(quote.source||'').replace(/\s*·\s*пересказ\b/gi,'').replace('Эвенкийские заповеди Иты (народные)','Эвенкийские заповеди Иты');
        let url='';
        try{const parsed=new URL(quote.sourceUrl,location.href);if(parsed.protocol==='https:'||parsed.protocol==='http:')url=parsed.href}catch(e){}
        if(url&&label){const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=label;sourceNode.append(link)}else sourceNode.textContent=label;
      }
      target.classList.remove('is-changing');
      try{localStorage.setItem(lastKey,String(index))}catch(e){}
    };
    if(animate)pendingUpdate=window.setTimeout(()=>{pendingUpdate=null;update()},450);else update();
  };
  const scheduleRotation=()=>{
    if(rotationTimer)window.clearInterval(rotationTimer);
    rotationTimer=window.setInterval(()=>{if(!document.hidden&&quotes.length>1)show(true)},12000);
  };
  const nextQuote=()=>{if(quotes.length>1)show(true);scheduleRotation()};
  band.addEventListener('click',event=>{
    if(event.target.closest('a'))return;
    nextQuote();
  });
  band.addEventListener('keydown',event=>{
    if(event.target===band&&(event.key==='Enter'||event.key===' ')){event.preventDefault();nextQuote()}
  });
  show(false);
  scheduleRotation();
})();
