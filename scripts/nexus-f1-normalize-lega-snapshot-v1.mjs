#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { normalizeMatchParticipation, buildSourceStints, auditOpportunityNormalization } from './lib/nexus-f1-opportunity-normalization-v1.mjs'
import { auditF1SurfaceIntegrity } from './lib/nexus-f1-surface-integrity-v1.mjs'

const ROOT=process.env.NEXUS_F1_LEGA_ROOT??'.nexus-f1-lega-snapshot-v1'
const hash=v=>crypto.createHash('sha256').update(v).digest('hex')
const read=p=>fs.readFileSync(p,'utf8')
const json=p=>JSON.parse(read(p))
const write=(p,v)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,v)}
const fail=m=>{throw new Error(`Nexus F1 Lega normalization: ${m}`)}
const stable=v=>JSON.stringify(v,null,2)+'\n'

const manifestPath=path.join(ROOT,'manifest.json'),auditPath=path.join(ROOT,'audit.json')
const manifestText=read(manifestPath),manifest=JSON.parse(manifestText),rawAudit=json(auditPath)
if(manifest.schema!=='NEXUS_F1_LEGA_RAW_SNAPSHOT_MANIFEST_V1'||manifest.protocolVersion!=='1.1')fail('raw manifest mismatch')
if(rawAudit.status!=='PASS_RAW_ACQUISITION_ONLY')fail('raw audit not PASS')
if(manifest.freshAcquisition!==true||manifest.oldArtifactReference?.freshSnapshotIsRecovery!==false)fail('fresh/recovery semantics invalid')
if(manifest.totals?.matches!==1900||manifest.totals?.lineupPayloads!==1900)fail(`expected 1900/1900, got ${manifest.totals?.matches}/${manifest.totals?.lineupPayloads}`)

const matchResults=[],sourceFiles=[]
for(const season of manifest.seasons){
  const seasonName=String(season.seasonName),matchesPath=season.matchesFile,matchesText=read(matchesPath)
  if(hash(matchesText)!==season.matchesSha256)fail(`${seasonName}: matches hash mismatch`)
  const matchesPayload=JSON.parse(matchesText),matches=Array.isArray(matchesPayload?.matches)?matchesPayload.matches:null
  if(!matches||matches.length!==380)fail(`${seasonName}: matches[] invalid`)
  const byId=new Map(matches.map(m=>[String(m.matchId??m.id),m]))
  sourceFiles.push({kind:'MATCH_CATALOG',season:seasonName,path:matchesPath,sha256:season.matchesSha256})
  for(const ref of season.lineups){
    const lineupText=read(ref.file),actual=hash(lineupText)
    if(actual!==ref.sha256)fail(`${seasonName}/${ref.matchId}: lineup hash mismatch`)
    const match=byId.get(String(ref.matchId));if(!match)fail(`${seasonName}/${ref.matchId}: missing catalog match`)
    if(String(match.matchDateUtc??'')!==String(ref.matchDateUtc??''))fail(`${seasonName}/${ref.matchId}: matchDate mismatch`)
    const result=normalizeMatchParticipation({season:seasonName,match,lineup:JSON.parse(lineupText),sourceHash:actual,capturedAt:ref.capturedAt})
    matchResults.push(result);sourceFiles.push({kind:'LINEUP',season:seasonName,matchId:String(ref.matchId),path:ref.file,sha256:actual})
  }
}
if(matchResults.length!==1900)fail(`normalization input matches ${matchResults.length} != 1900`)
const records=matchResults.flatMap(x=>x.records).sort((a,b)=>a.season.localeCompare(b.season)||a.matchDateUtc.localeCompare(b.matchDateUtc)||a.sourceMatchId.localeCompare(b.sourceMatchId)||a.sourcePlayerId.localeCompare(b.sourcePlayerId))
const stints=buildSourceStints(records),normalizationAudit=auditOpportunityNormalization({matchResults,stints}),integrity=auditF1SurfaceIntegrity({opportunityRecords:records,opportunityStints:stints})
if(integrity.status!=='PASS')fail(`surface integrity FAIL ${JSON.stringify(integrity.violations.slice(0,20))}`)
const quarantined=matchResults.filter(x=>x.status==='QUARANTINED').map(x=>({season:x.season,sourceMatchId:x.sourceMatchId,matchDateUtc:x.matchDateUtc,quarantineReasons:x.quarantineReasons,affectedTeamIds:x.affectedTeamIds}))
const out=path.join(ROOT,'normalized')
const participationText=records.map(x=>JSON.stringify(x)).join('\n')+(records.length?'\n':'')
const stintDataset={schema:'NEXUS_F1_OPPORTUNITY_SOURCE_STINT_DATASET_V1',protocolVersion:'1.1',sourceSnapshotManifestSha256:hash(manifestText),sourceFamily:'OPPORTUNITY_PARTICIPATION',minutesConvention:'REGULATION_90_CLOCK_V1',canonicalIdentityApplied:false,d1IdentityAuthorityRequiredForCanonicalJoin:true,expectedMinutesBuilt:false,trainingPromotionGranted:false,canonicalMutation:false,records:stints}
const stintsText=stable(stintDataset)
const audit={schema:'NEXUS_F1_OPPORTUNITY_NORMALIZATION_AUDIT_V1',protocolVersion:'1.1',status:'PASS',sourceSnapshotManifestSha256:hash(manifestText),sourceRawAuditSha256:hash(read(auditPath)),normalizationAudit,integrity,quarantinedMatches:quarantined,sourceFiles,outputs:{participationSha256:hash(participationText),sourceStintsSha256:hash(stintsText)},governance:{canonicalIdentityApplied:false,expectedMinutesBuilt:false,trainingPromotionGranted:false,f1Closed:false,f2PlusAuthorized:false,canonicalMutation:false}}
const auditText=stable(audit)
write(path.join(out,'opportunity-participation-raw-v1.ndjson'),participationText)
write(path.join(out,'opportunity-source-stints-v1.json'),stintsText)
write(path.join(out,'opportunity-normalization-audit-v1.json'),auditText)
write(path.join(out,'NORMALIZED.sha256'),`${hash(participationText)}  opportunity-participation-raw-v1.ndjson\n${hash(stintsText)}  opportunity-source-stints-v1.json\n${hash(auditText)}  opportunity-normalization-audit-v1.json\n`)
console.log(JSON.stringify({status:'PASS',matchesInput:matchResults.length,matchesAdmitted:normalizationAudit.matchesAdmitted,matchesQuarantined:normalizationAudit.matchesQuarantined,participationRecords:records.length,sourceStints:stints.length,integrity:integrity.status,participationSha256:hash(participationText),sourceStintsSha256:hash(stintsText),auditSha256:hash(auditText)},null,2))
