/** Object-API observations, not pixel verification or a trading conclusion. */
import { drawingInventory } from './chart-observation.ts'

export const FEEDBACK_KINDS=['horizontal_line','trend_line','channel','rectangle']
export const FEEDBACK_STATUSES=['created','hidden','removed','failed','unknown']
export const FEEDBACK_REASONS=['overlay_registered','period_mismatch','anchors_not_loaded','outside_time_viewport',
  'invalid_geometry','overlay_missing','overlay_mismatch','overlay_api_unavailable','overlay_lookup_failed',
  'overlay_removed','overlay_still_present','context_not_ready','application_rolled_back','rollback_unknown','creation_failed']
const PHASES=['current','applied','rolled_back','rollback_unknown']
const STATUS_REASONS:any={created:['overlay_registered','outside_time_viewport'],hidden:['period_mismatch','anchors_not_loaded'],
  removed:['overlay_removed'],failed:['invalid_geometry','overlay_missing','overlay_mismatch','overlay_still_present','creation_failed'],
  unknown:['overlay_api_unavailable','overlay_lookup_failed','overlay_mismatch','context_not_ready','application_rolled_back','rollback_unknown']}
function empty(status:string) {return {schema_version:1,report_status:status,evidence_scope:'chart_object_api',render_verified:false,pixel_verified:false,items:[]}}
export function sanitizeDrawingFeedback(raw:any, allowed:any[]):any {
  if(raw==null)return empty('not_reported')
  if(['not_reported','invalid'].includes(raw.report_status))return empty(raw.report_status)
  try {
    if(raw.schema_version!==1 || !PHASES.includes(raw.phase) || !Array.isArray(raw.items) || raw.items.length>360)throw Error('invalid_report')
    const objects=new Map(allowed.map(d=>[d.id,d.kind])), seen=new Set<string>()
    const items=raw.items.map((item:any)=>{
      if(typeof item.id!=='string' || !item.id || item.id.length>256 || objects.get(item.id)!==item.kind || seen.has(item.id)
        || !FEEDBACK_KINDS.includes(item.kind) || !FEEDBACK_STATUSES.includes(item.status) || !FEEDBACK_REASONS.includes(item.reason)
        || !STATUS_REASONS[item.status].includes(item.reason)
        || !['unknown','outside_time_viewport','not_applicable'].includes(item.visibility))throw Error('invalid_item')
      if((item.reason==='outside_time_viewport')!==(item.visibility==='outside_time_viewport'))throw Error('invalid_visibility')
      seen.add(item.id)
      return {id:item.id,kind:item.kind,status:item.status,reason:item.reason,visibility:item.visibility,
        outside_loaded_price_envelope:item.outside_loaded_price_envelope===true}
    })
    if(seen.size!==objects.size)throw Error('incomplete_report')
    return {...empty('reported'),phase:raw.phase,items}
  } catch {return empty('invalid')}
}

function expectedOverlay(command:any, rows:any[], interval:string, times:Set<number>):any {
  const types:any={DRAW_HORIZONTAL_LINE:['ftvHorizontalLine','agentHorizontalLines'],DRAW_AGENT_TREND_LINE:['ftvTrendLine','agentTrendLines'],
    DRAW_AGENT_CHANNEL:['ftvAgentChannel','agentChannels'],DRAW_AGENT_RECTANGLE:['ftvAgentRectangle','agentRectangles']}
  const point=(p:any)=>({timestamp:Number(p?.time)*1000,value:Number(p?.price)})
  const type=command.type
  if(['DRAW_AGENT_CHANNEL','DRAW_AGENT_RECTANGLE'].includes(type) && command.interval!==interval)return {skip:'period_mismatch'}
  let points:any[], sourceTimes:number[]=[]
  if(type==='DRAW_HORIZONTAL_LINE') points=[{timestamp:rows.at(-1)?.time*1000,value:Number(command.price)}]
  else if(type==='DRAW_AGENT_RECTANGLE') {
    sourceTimes=[command.start_time,command.end_time]
    points=[{timestamp:command.start_time*1000,value:command.upper_price},{timestamp:command.end_time*1000,value:command.lower_price}]
    if(!(command.start_time<command.end_time && command.lower_price>0 && command.lower_price<command.upper_price))return {failure:'invalid_geometry'}
  } else {
    sourceTimes=[command.from?.time,command.to?.time,...(type==='DRAW_AGENT_CHANNEL' ? [command.parallel?.time] : [])]
    if(!(command.from?.time<command.to?.time))return {failure:'invalid_geometry'}
    points=type==='DRAW_AGENT_CHANNEL' ? [command.upper?.from,command.upper?.to,command.lower?.from,command.lower?.to].map(point)
      : [command.from,command.to].map(point)
    if(type==='DRAW_AGENT_CHANNEL' && (command.geometry_basis!=='candle_index_linear_price'
      || !command.parallel || command.parallel.time<command.from.time || command.parallel.time>command.to.time))return {failure:'invalid_geometry'}
  }
  if(points.some(p=>!Number.isFinite(p.timestamp) || !Number.isFinite(p.value) || p.value<=0))return {failure:'invalid_geometry'}
  if(sourceTimes.some(time=>!times.has(time)))return {skip:'anchors_not_loaded'}
  return {name:types[type][0],group:types[type][1],points}
}

export function collectDrawingFeedback(payload:any, context:any, chart:any, previous:any[]=[], phase='current'):any {
  const commands=payload?.chartCommands ?? [], inventory=drawingInventory(payload ?? {})
  const after=new Set(inventory.map(d=>d.id)), before=drawingInventory({chartCommands:previous,interval:payload?.interval})
  const deleted=before.filter(d=>!after.has(d.id)), rows=context?.candles ?? []
  const times=new Set<number>(rows.map((r:any)=>r.time))
  const ready=context?.state==='ready' && rows.length>0
  let canRead=false
  try {canRead=typeof chart?.getOverlayById==='function'}catch {}
  const lookup=(id:string)=>{try{return {value:chart.getOverlayById(id)}}catch{return {error:true}}}
  const viewport=context?.visible_range
  const first=viewport?.available && rows[viewport.index_from]?.time
  const last=viewport?.available && viewport.index_to_exclusive>viewport.index_from && rows[viewport.index_to_exclusive-1]?.time
  const low=rows.length ? Math.min(...rows.map((r:any)=>r.low)) : NaN, high=rows.length ? Math.max(...rows.map((r:any)=>r.high)) : NaN
  const items=inventory.map((drawing:any)=>{
    const cmd=commands.find((c:any)=>c.id===drawing.id), item:any={id:drawing.id,kind:drawing.kind,status:'unknown',
      reason:'context_not_ready',visibility:'unknown',outside_loaded_price_envelope:false}
    if(!ready)return item
    if(phase==='rolled_back' || phase==='rollback_unknown') {
      item.reason=phase==='rolled_back' ? 'application_rolled_back' : 'rollback_unknown';return item
    }
    const expected=expectedOverlay(cmd,rows,context.ui_interval || context.interval,times)
    const prices=expected.points?.map((p:any)=>p.value) ?? []
    item.outside_loaded_price_envelope=prices.some((p:number)=>p<low || p>high)
    if(!canRead) {item.reason='overlay_api_unavailable';return item}
    const observed=lookup(drawing.id)
    if(observed.error){item.reason='overlay_lookup_failed';return item}
    if(expected.skip) {
      item.status=observed.value ? 'unknown' : 'hidden';item.reason=observed.value ? 'overlay_mismatch' : expected.skip
      item.visibility='not_applicable';return item
    }
    if(expected.failure) {item.status='failed';item.reason=expected.failure;return item}
    if(!observed.value){item.status='failed';item.reason='overlay_missing';return item}
    const overlay=observed.value
    let same=false
    try {
      const actual=overlay.points
      same=overlay.id===drawing.id && overlay.name===expected.name && overlay.groupId===expected.group && Array.isArray(actual)
        && actual.length===expected.points.length && actual.every((p:any,i:number)=>p.timestamp===expected.points[i].timestamp
          && Number.isFinite(p.value) && Math.abs(p.value-expected.points[i].value)<=Math.max(1,Math.abs(p.value))*1e-10)
        && overlay.extendData?.label===(cmd.label || '') && overlay.extendData?.colorName===(cmd.color || 'info')
        && (drawing.kind!=='channel' || overlay.extendData?.showMidline===(cmd.show_midline!==false))
        && (drawing.kind!=='rectangle' || overlay.extendData?.showFill===(cmd.show_fill!==false))
    } catch {item.reason='overlay_lookup_failed';return item}
    item.status=same ? 'created' : 'failed';item.reason=same ? 'overlay_registered' : 'overlay_mismatch'
    if(same && drawing.kind!=='horizontal_line' && first && last) {
      const min=Math.min(...expected.points.map((p:any)=>p.timestamp/1000)), max=Math.max(...expected.points.map((p:any)=>p.timestamp/1000))
      if(max<first || min>last){item.visibility='outside_time_viewport';item.reason='outside_time_viewport'}
    }
    return item
  })
  for(const drawing of deleted) {
    if(phase==='rolled_back' || phase==='rollback_unknown') {
      items.push({id:drawing.id,kind:drawing.kind,status:'unknown',reason:phase==='rolled_back' ? 'application_rolled_back' : 'rollback_unknown',
        visibility:'not_applicable',outside_loaded_price_envelope:false});continue
    }
    if(!ready) {
      items.push({id:drawing.id,kind:drawing.kind,status:'unknown',reason:'context_not_ready',
        visibility:'not_applicable',outside_loaded_price_envelope:false});continue
    }
    const observed=canRead ? lookup(drawing.id) : {error:true}
    items.push({id:drawing.id,kind:drawing.kind,status:observed.error ? 'unknown' : observed.value ? 'failed' : 'removed',
      reason:observed.error ? (canRead ? 'overlay_lookup_failed' : 'overlay_api_unavailable') : observed.value ? 'overlay_still_present' : 'overlay_removed',visibility:'not_applicable',
      outside_loaded_price_envelope:false})
  }
  return {schema_version:1,phase,evidence_scope:'chart_object_api',render_verified:false,pixel_verified:false,items}
}
