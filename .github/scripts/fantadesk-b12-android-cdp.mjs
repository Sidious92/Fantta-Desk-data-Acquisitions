// CI-only, no tokens or page content are printed: evaluate guest UI state over debug WebView CDP.
const endpoint = 'http://127.0.0.1:9222/json';
const controller = new AbortController();
const timeout=setTimeout(()=>controller.abort(),7000);
try {
  const response=await fetch(endpoint,{signal:controller.signal});
  if(!response.ok)throw Error('WEBVIEW_CDP_HTTP_'+response.status);
  const targets=await response.json();
  const page=targets.find(t=>t.type==='page' && typeof t.webSocketDebuggerUrl==='string');
  if(!page)throw Error('WEBVIEW_CDP_TARGET_MISSING');
  const ws=new WebSocket(page.webSocketDebuggerUrl.replace(/^ws:\/\/(?:localhost|127\.0\.0\.1):\d+/, 'ws://127.0.0.1:9222'));
  const result=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('WEBVIEW_CDP_TIMEOUT')),9000);
    ws.addEventListener('error',()=>{clearTimeout(timer);reject(Error('WEBVIEW_CDP_SOCKET_ERROR'));});
    ws.addEventListener('open',()=>ws.send(JSON.stringify({id:17,method:'Runtime.evaluate',params:{
      returnByValue:true,
      expression:"(()=>({title:document.title,heading:document.querySelector('h1')?.textContent||'',width:window.innerWidth,documentWidth:document.documentElement.scrollWidth,googleButton:Array.from(document.querySelectorAll('button')).some(el=>/Continua con Google/.test(el.textContent||''))}))()"
    }})));
    ws.addEventListener('message',event=>{
      const json=JSON.parse(event.data);
      if(json.id!==17)return;
      clearTimeout(timer);
      if(json.error||json.result?.exceptionDetails)reject(Error('WEBVIEW_CDP_EVALUATION_FAILED'));
      else resolve(json.result?.result?.value);
    });
  });
  ws.close();
  console.log('WEBVIEW_CDP_DIAGNOSTIC '+JSON.stringify({headingMatchesLogin:result?.heading==='Accedi',width:result?.width,documentWidth:result?.documentWidth,googleButton:result?.googleButton}));
  if(result?.heading!=='Accedi')throw Error('WEBVIEW_LOGIN_NOT_RENDERED');
  if(result?.googleButton!==false)throw Error('WEBVIEW_NATIVE_GOOGLE_SHOULD_BE_DISABLED');
  if(!Number.isFinite(result.width)||result.width>440||result.documentWidth>result.width+1)throw Error('WEBVIEW_VIEWPORT_OVERFLOW');
  console.log('WEBVIEW_GUEST_LOGIN_CDP_PASS');
} catch (error) {
  console.error('WEBVIEW_CDP_CHECK_FAILED: '+error.message);
  process.exitCode=1;
} finally {clearTimeout(timeout);}
