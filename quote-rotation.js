(()=>{
  const target=document.getElementById('siteQuoteText');
  if(!target)return;
  const sourceNode=document.getElementById('siteQuoteSource');
  const defaults=window.TAEZHNAYA_QUOTES||[];
  const savedKey='taezhnaya-nit-quotes-v3';
  const lastKey='taezhnaya-nit-shared-last-quote-v1';
  let quotes=defaults;
  try{const saved=JSON.parse(localStorage.getItem(savedKey));if(Array.isArray(saved)&&saved.length)quotes=saved.filter(q=>q&&typeof q.text==='string'&&q.text.trim())}catch(e){}
  if(!quotes.length)return;
  let index=-1;
  try{const previous=Number(localStorage.getItem(lastKey));if(Number.isInteger(previous)&&previous>=0&&previous<quotes.length)index=previous}catch(e){}
  const show=(animate=false)=>{
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
    if(animate)window.setTimeout(update,450);else update();
  };
  show(false);
  window.setInterval(()=>{if(!document.hidden&&quotes.length>1)show(true)},12000);
})();
