// Adapt the upstream page's fetch API to the iOS host without changing its markup.
(() => {
  const native = (path, data = {}) => window.webkit.messageHandlers.mobile.postMessage({path,data});
  const json = (value, status = 200) => new Response(JSON.stringify(value), {status,headers:{'Content-Type':'application/json'}});
  const originalFetch = window.fetch.bind(window);
  let lastNotice = '';
  window.fetch = async (url, options = {}) => {
    if (typeof url !== 'string' || !url.startsWith('/api/')) return originalFetch(url,options);
    try {
      if (options.body && typeof options.body !== 'string') throw Error('افتح ملفات المشروع من إعدادات الجهاز');
      const body = options.body ? JSON.parse(options.body) : {};
      const data = await native(url,{...body,method:options.method || 'GET'});
      if (url === '/api/state') {
        syncProject(data);
        if (data.notice && data.notice !== lastNotice) banner(data.notice, true);
        lastNotice = data.notice || '';
      }
      if (url !== '/api/chat') return json(data);
      const part = {kind:'text',text:data.answer};
      const events = [{type:'conversation',id:data.id},{type:'text',text:data.answer},{type:'saved',meta:{parts:[part]}}];
      return new Response(events.map(e=>JSON.stringify(e)+'\n').join(''),{headers:{'Content-Type':'application/x-ndjson'}});
    } catch (e) { return json({error:e.message || String(e)},400); }
  };
  // The native share sheet handles conversation exports on iOS.
  document.addEventListener('click',e=>{
    const button=e.target.closest?.('button[data-act="exp"]');
    const conversation=button?.closest('.conv[data-id]');
    if (!conversation) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    native('/api/conversations/'+encodeURIComponent(conversation.dataset.id)+'/export')
      .catch(error=>window.alert(error.message));
  },true);
  let activeProject;
  function syncProject(folder) {
    if (!folder.project || !folder.project_id) return;
    const switched = activeProject !== undefined && activeProject !== folder.project_id;
    activeProject = folder.project_id;
    LS.set('project', folder.project);
    S.project = folder.project;
    if (switched) {
      S.savedFolder = null;
      S.pview = null;
      S.handoffFrom = null;
      setTab('chats');
      newChat(false);
    }
    showProject();
    const label = document.documentElement.lang === 'ar' ? 'مجلد المشروع' : 'Project folder';
    document.getElementById('projectBtn').setAttribute('aria-label', label + ': ' + folder.project);
  }
  async function chooseProject() {
    try {
      const folder = await native('/api/project');
      if (folder.project_id) syncProject(folder);
    } catch (error) {
      banner(error.message || String(error), true);
    }
  }
  function installLayout() {
    const byId = id => document.getElementById(id);
    const app = byId('app'), sidebar = byId('sidebar'), main = app.querySelector('main');
    const menu = byId('sideBtn'), send = byId('send'), row = send.parentElement;
    const drawer = matchMedia('(max-width: 900px), (max-height: 520px)');
    const toolbar = matchMedia('(max-width: 1100px), (max-height: 520px)');
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'responsive.css';
    document.head.append(css);

    const headerTools = document.createElement('div');
    headerTools.id = 'mobileHeaderTools';
    const top = byId('topbar');
    headerTools.append(...Array.from(top.children).slice(2));
    top.append(headerTools);
    function positionSend() {
      if (toolbar.matches) row.before(send);
      else row.append(send);
    }
    positionSend();
    toolbar.addEventListener('change', positionSend);

    const backdrop = document.createElement('div');
    backdrop.id = 'drawerBackdrop';
    backdrop.setAttribute('aria-hidden','true');
    sidebar.after(backdrop);
    const close = document.createElement('button');
    close.id = 'drawerClose';
    close.className = 'btn ghost';
    close.textContent = '×';
    sidebar.querySelector('.brand').append(close);
    menu.setAttribute('aria-controls', sidebar.id);
    function labelMenu() {
      const arabic = document.documentElement.lang === 'ar';
      menu.setAttribute('aria-label', arabic ? 'قائمة المحادثات والمشاريع' : 'Chats and projects');
      close.setAttribute('aria-label', arabic ? 'إغلاق القائمة' : 'Close menu');
    }
    labelMenu();
    new MutationObserver(labelMenu).observe(document.documentElement, {attributes:true, attributeFilter:['lang']});
    function showSidebar(show, moveFocus = false) {
      main.inert = drawer.matches && show;
      app.classList.toggle('side-hidden', !show);
      menu.setAttribute('aria-expanded', String(show));
      if (moveFocus) (show && drawer.matches ? close : menu).focus({preventScroll:true});
    }
    function applyWidth() { showSidebar(!drawer.matches); }
    applyWidth();
    drawer.addEventListener('change', applyWidth);
    menu.onclick = () => showSidebar(app.classList.contains('side-hidden'), true);
    close.onclick = backdrop.onclick = () => showSidebar(false, true);
    sidebar.addEventListener('click', event => {
      if (drawer.matches && event.target.closest('#newChat, .conv') && !event.target.closest('[data-act]')) {
        showSidebar(false, true);
      }
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && drawer.matches && !app.classList.contains('side-hidden') && !byId('overlay').classList.contains('show')) {
        showSidebar(false, true);
      }
    });
    const viewport = window.visualViewport;
    if (viewport) {
      const resize = () => {
        if (Math.abs(viewport.scale - 1) < .02) {
          document.documentElement.style.setProperty('--visible-height', viewport.height + 'px');
        }
      };
      resize();
      viewport.addEventListener('resize', resize);
    }
  }
  window.addEventListener('DOMContentLoaded',()=>{
    installLayout();
    document.getElementById('projectBtn').onclick = chooseProject;
    // The Files picker can open an existing folder or create a new one.
    document.addEventListener('click', event => {
      if (event.target.closest('#pvNew') || (S.tab === 'projects' && event.target.closest('#newChat'))) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!document.getElementById('app').classList.contains('side-hidden') &&
            getComputedStyle(document.getElementById('sidebar')).position === 'absolute') {
          document.getElementById('drawerClose').click();
        }
        chooseProject();
      }
    }, true);
    const version=document.getElementById('ver');
    version.setAttribute('role','button'); version.tabIndex=0;
    version.title='إعدادات الجهاز والاتصال';
    version.onclick=()=>native('/mobile/options');
    version.onkeydown=e=>{if(e.key==='Enter') version.click();};
  });
})();
