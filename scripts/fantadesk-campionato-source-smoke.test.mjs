import test from 'node:test';
import assert from 'node:assert/strict';
import {summarizeOpenFootball,summarizeStatsBomb,summarizeWikidata,redactError} from './source-smoke-utils.mjs';
test('OpenFootball counts completed and overdue fixtures',()=>{
 const d={name:'Test',matches:[{date:'2026-10-10',team1:'A',team2:'B',score:{ft:[1,2]}},{date:'2026-10-12',team1:'A',team2:'C'},{date:'2026-12-02',team1:'B',team2:'C'}]};
 assert.deepEqual(summarizeOpenFootball(d,new Date('2026-10-22T00:00:00Z')),{season:'Test',matches:3,completed:1,overdue:1,teams:3});
});
test('StatsBomb only Italy Serie A male seasons',()=>assert.deepEqual(summarizeStatsBomb([{country_name:'Italy',competition_name:'Serie A',season_name:'2015/2016'},{country_name:'Italy',competition_name:'Serie A Women',season_name:'2023/2024'}]),{competitionSeasons:['2015/2016']}));
test('Wikidata DOB property',()=>assert.deepEqual(summarizeWikidata({entities:{Q615:{id:'Q615',labels:{en:{value:'Lionel Messi'}},claims:{P569:[{}]}}}}),{entityId:'Q615',name:'Lionel Messi',dateOfBirthPresent:true}));
test('secret redaction',()=>assert.equal(redactError('x-auth-token: supersecret'),'x-auth-token=<REDACTED>'));
