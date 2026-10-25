import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const browser = await chromium.launch({ headless:true, args:['--no-sandbox'] });
const url='http://127.0.0.1:4173';
let count=0;
try {
  for(const device of [{name:'desktop',w:1440,h:900},{name:'mobile',w:390,h:844},{name:'mobile-small',w:360,h:740}]) {
    const context=await browser.newContext({viewport:{width:device.w,height:device.h},isMobile:device.name!=='desktop',deviceScaleFactor:1});
    const page=await context.newPage();
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url+'/',{waitUntil:'domcontentloaded'});
    await page.getByRole('heading',{name:'Accedi',exact:true}).waitFor({timeout:20000});
    assert.equal(await page.getByRole('button',{name:'Continua con Google'}).count(),0,'Google must stay disabled');
    assert.equal(await page.getByText('CONTENUTO PRIVATO').count(),0);
    if(device.name!=='desktop') {
      const hit=await page.getByRole('button',{name:'Non hai un account? Crealo'}).evaluate(el=>{
        const r=el.getBoundingClientRect();
        const x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2);
        const node=document.elementFromPoint(x,y);
        return {width:innerWidth,height:innerHeight,scrollY,docHeight:document.documentElement.scrollHeight,button:{x:r.x,y:r.y,w:r.width,h:r.height},hitTag:node?.tagName,hitClass:typeof node?.className==='string'?node.className:''};
      });
      console.log('MOBILE_HIT_TEST_DIAGNOSTIC '+device.name+' '+JSON.stringify(hit));
    }
    await page.getByRole('button',{name:'Non hai un account? Crealo'}).click({timeout:7500});
    await page.getByRole('heading',{name:'Crea account',exact:true}).waitFor();
    assert.equal(await page.locator('input[type="password"]').count(),2);
    await page.getByRole('button',{name:'Torna all’accesso'}).click();
    await page.getByRole('button',{name:'Password dimenticata?'}).click();
    await page.getByRole('heading',{name:'Recupera password'}).waitFor();
    assert.equal(await page.locator('input[type="password"]').count(),0);
    await page.getByRole('button',{name:'Torna all’accesso'}).click();
    const widths=await page.evaluate(()=>({screen:window.innerWidth,doc:document.documentElement.scrollWidth}));
    assert.ok(widths.doc<=widths.screen+1,'Horizontal overflow '+JSON.stringify(widths));
    assert.deepEqual(errors,[],'Browser JS exception');
    console.log('GUEST_BROWSER_PASS_'+device.name.toUpperCase()+' '+device.w+'x'+device.h);
    await page.goto(url+'/leagues',{waitUntil:'domcontentloaded'});
    await page.getByRole('heading',{name:'Accedi',exact:true}).waitFor({timeout:20000});
    assert.ok(!page.url().includes('/account'),'Unexpected private redirect');
    await page.goto(url+'/account-deletion',{waitUntil:'domcontentloaded'});
    await page.locator('body').getByText(/eliminazione|cancellazione|Elimina account/i).first().waitFor({timeout:20000});
    assert.deepEqual(errors,[],'Browser JS error at public deletion route');
    console.log('GUEST_DEEPLINK_AND_PUBLIC_DELETE_PASS_'+device.name.toUpperCase());
    await context.close();
    count+=1;
  }
  console.log('FANTADESK_B12_GUEST_WEB_E2E_PASS '+count+' viewport sizes; no signups, emails, login or deletion API calls');
} finally { await browser.close(); }
