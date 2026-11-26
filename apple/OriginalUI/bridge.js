// Adapt the upstream page's fetch API to the iOS host without changing its markup.
(() => {
  const native = (path, data = {}) => window.webkit.messageHandlers.mobile.postMessage({path,data});
  const json = (value, status = 200) => new Response(JSON.stringify(value), {status,headers:{'Content-Type':'application/json'}});
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (url, options = {}) => {
    if (typeof url !== 'string' || !url.startsWith('/api/')) return originalFetch(url,options);
    try {
      if (options.body && typeof options.body !== 'string') throw Error('افتح ملفات المشروع من إعدادات الجهاز');
      const body = options.body ? JSON.parse(options.body) : {};
      const data = await native(url,{...body,method:options.method || 'GET'});
      if (url !== '/api/chat') return json(data);
      const part = {kind:'text',text:data.answer};
      const events = [{type:'conversation',id:data.id},{type:'text',text:data.answer},{type:'saved',meta:{parts:[part]}}];
      return new Response(events.map(e=>JSON.stringify(e)+'\n').join(''),{headers:{'Content-Type':'application/x-ndjson'}});
    } catch (e) { return json({error:e.message || String(e)},400); }
  };
  window.addEventListener('DOMContentLoaded',()=>{
    const version=document.getElementById('ver');
    version.setAttribute('role','button'); version.tabIndex=0;
    version.title='إعدادات الجهاز والاتصال';
    version.onclick=()=>native('/mobile/options');
    version.onkeydown=e=>{if(e.key==='Enter') version.click();};
  });
})();
