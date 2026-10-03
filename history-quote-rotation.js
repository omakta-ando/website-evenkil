(()=>{
  const savedKey="taezhnaya-nit-quotes-v3";
  const lastKey="taezhnaya-nit-history-last-quote-v1";
  const defaults=window.TAEZHNAYA_QUOTES||[];
  let quotes=defaults;
  try {
    const saved=JSON.parse(localStorage.getItem(savedKey));
    if(Array.isArray(saved)&&saved.length>1) quotes=saved;
  } catch(e) {}
  if(quotes.length<2) return;
  let previous=-1;
  try {
    const stored=localStorage.getItem(lastKey);
    if(stored!==null) previous=Number(stored);
  } catch(e) {}
  let index=Math.floor(Math.random()*quotes.length);
  if(Number.isInteger(previous)&&previous>=0&&previous<quotes.length) index=(previous+1)%quotes.length;
  try { localStorage.setItem(lastKey,String(index)); } catch(e) {}
  const quote=quotes[index];
  const text=document.getElementById("knowledgeQuoteText");
  const source=document.getElementById("knowledgeQuoteSource");
  if(text) text.textContent=quote.text||"";
  if(source) {
    source.replaceChildren();
    const label=String(quote.source||"")
      .replace(/\s*·\s*пересказ\b/gi,"")
      .replace("Эвенкийские заповеди Иты (народные)","Эвенкийские заповеди Иты");
    let url="";
    try {
      const parsed=new URL(quote.sourceUrl,location.href);
      if(parsed.protocol==="https:"||parsed.protocol==="http:") url=parsed.href;
    } catch(e) {}
    if(url) {
      const link=document.createElement("a");
      link.href=url; link.target="_blank"; link.rel="noopener noreferrer";
      link.textContent=label||"Источник"; source.append(link);
    } else source.textContent=label;
  }
})();
