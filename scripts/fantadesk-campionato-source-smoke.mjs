#!/usr/bin/env node
// Bounded read-only source verification for FantaDesk Campionato.
// IMPORTANT: no user credentials, raw player datasets, or unlicensed source material are persisted.
import {writeFile,mkdir} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {summarizeOpenFootball,summarizeStatsBomb,summarizeWikidata,redactError} from './source-smoke-utils.mjs';

const now=new Date(),results=[];
const sportsKey=process.env.API_FOOTBALL_KEY?.trim();
const footballDataKey=process.env.FOOTBALL_DATA_KEY?.trim();
async function get(url,headers={}){
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),15000);
 try {
  const r=await fetch(url,{headers:{'User-Agent':'FantaDesk-Source-Smoke/0.1 (bounded read-only validation)',Accept:'application/json',...headers},signal:controller.signal});
  const body=await r.text(); let data=null;try{data=JSON.parse(body)}catch{}
  return {status:r.status,data};
 } finally {clearTimeout(timer)}
}
async function check(source,fn){
 try { results.push({source,...await fn()}) }
 catch(err){ results.push({source,status:'FAIL',reason:redactError(err?.message??err)}) }
}
await check('wikidata',async()=>{
 const r=await get('https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q615&props=labels%7Cclaims&languages=en&format=json');
 if(r.status!==200)return{status:'FAIL',httpStatus:r.status};
 const x=summarizeWikidata(r.data);
 return{status:x.name&&x.dateOfBirthPresent?'PASS':'FAIL',...x};
});
await check('openfootball',async()=>{
 const r=await get('https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/it.1.json');
 if(r.status!==200)return{status:'FAIL',httpStatus:r.status};
 const x=summarizeOpenFootball(r.data,now);
 return{status:(x.matches!==380||x.teams!==20)?'FAIL':x.overdue?'WARN_STALE':'PASS',...x};
});
await check('statsbomb-open',async()=>{
 const r=await get('https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json');
 if(r.status!==200)return{status:'FAIL',httpStatus:r.status};
 const x=summarizeStatsBomb(r.data);
 return{status:x.competitionSeasons.length>0?'PASS':'FAIL',...x};
});
await check('football-data.org',async()=>{
 if(!footballDataKey)return{status:'SKIP_NO_KEY',reason:'FOOTBALL_DATA_KEY not configured'};
 const h={'X-Auth-Token':footballDataKey};
 const a=await get('https://api.football-data.org/v4/competitions/SA/matches?season=2026',h);
 if(a.status!==200)return{status:'FAIL',matchesHttpStatus:a.status};
 const b=await get('https://api.football-data.org/v4/competitions/SA/standings?season=2026',h);
 const matches=a.data?.matches??[];
 return{status:matches.length?'PASS':'PARTIAL',matchesHttpStatus:a.status,standingsHttpStatus:b.status,fixtureCount:matches.length,finished:matches.filter(x=>x.status==='FINISHED').length,standingsRows:b.data?.standings?.[0]?.table?.length??null};
});
await check('api-football',async()=>{
 if(!sportsKey)return{status:'SKIP_NO_KEY',reason:'API_FOOTBALL_KEY not configured'};
 const h={'x-apisports-key':sportsKey},base='https://v3.football.api-sports.io';
 const a=await get(base+'/status',h);
 const b=await get(base+'/leagues?id=135&season=2026',h);
 const c=await get(base+'/fixtures?league=135&season=2026&from=2026-10-10&to=2026-10-20',h);
 const fixtures=c.data?.response??[];
 const info={subscriptionHttpStatus:a.status,plan:a.data?.response?.subscription?.plan??null,seasonListed:(b.data?.response?.length??0)>0,leagueHttpStatus:b.status,fixturesHttpStatus:c.status,fixtureCount:fixtures.length,apiErrors:c.data?.errors&&Object.keys(c.data.errors).length?c.data.errors:null};
 if(c.status!==200||info.apiErrors)return{status:'FAIL',...info};
 if(!fixtures.length)return{status:'PARTIAL',...info,reason:'No fixtures in specified recent window'};
 const fixtureId=(fixtures.find(x=>x.fixture?.status?.short==='FT')??fixtures[0])?.fixture?.id;
 if(!fixtureId)return{status:'PARTIAL',...info,reason:'No fixture identifier'};
 const details={};
 for(const name of ['players','lineups','events','statistics']){
  const r=await get(base+'/fixtures/'+name+'?fixture='+fixtureId,h);
  details[name]={httpStatus:r.status,resultCount:r.data?.results??null,hasData:(r.data?.response?.length??0)>0};
 }
 const injury=await get(base+'/injuries?league=135&season=2026',h);
 details.injuries={httpStatus:injury.status,resultCount:injury.data?.results??null,hasData:(injury.data?.response?.length??0)>0};
 return{status:info.seasonListed&&Object.values(details).some(x=>x.hasData)?'PASS':'PARTIAL',...info,fixtureId,details};
});
await check('understat',async()=>({status:'SKIP_RIGHTS',reason:'Current-season browser data confirmed separately; scheduled automated acquisition requires usage-rights verification'}));
const report={schema:'FANTADESK_CAMPIONATO_SOURCE_SMOKE_V1',asOf:now.toISOString(),publicRepoOnly:true,noCredentialsLogged:true,results};
const output=resolve(process.env.FANTADESK_SMOKE_REPORT??'/tmp/fantadesk-campionato-source-smoke.json');
await mkdir(dirname(output),{recursive:true});await writeFile(output,JSON.stringify(report,null,2)+'\n','utf8');
console.log(JSON.stringify(report,null,2));
if(results.some(x=>x.status==='FAIL'))process.exitCode=1;
