import { sanitizePriceSource, sanitizePriceCondition } from './price-series.ts'

const COLORS=new Set(['info','warning','success','danger'])
const INTERVALS=new Set(['minute','day','week','month','quarter','year'])

/** A bounded sequence of independent vertical price sticks. */
export function sanitizePriceSticksCommand(raw:any,expectedBars:number,interval:string):any {
  if(raw?.type!=='DRAW_AGENT_PRICE_STICKS' || typeof raw.id!=='string' || !/^sticks_[a-f0-9]{24}$/.test(raw.id)
    || !INTERVALS.has(raw.interval) || !COLORS.has(raw.color) || typeof raw.label!=='string' || raw.label.length>48
    || !/^[a-f0-9]{64}$/.test(raw.sticks_hash) || raw.row_hash!=null && !/^[a-f0-9]{16}$/.test(raw.row_hash)
    || !Number.isSafeInteger(raw.bar_count) || raw.bar_count<1 || raw.bar_count>4000
    || raw.interval===interval && raw.bar_count!==expectedBars
    || !Array.isArray(raw.start_values) || !Array.isArray(raw.end_values)
    || raw.start_values.length!==raw.bar_count || raw.end_values.length!==raw.bar_count)throw Error('invalid_source_sticks')
  let present=0
  for(let i=0;i<raw.bar_count;i++) {
    const start=raw.start_values[i],end=raw.end_values[i]
    if(start===null && end===null)continue
    if(typeof start!=='number' || typeof end!=='number' || !Number.isFinite(start) || !Number.isFinite(end)
      || start<=0 || end<=0 || start===end)throw Error('invalid_source_sticks')
    present++
  }
  if(!present)throw Error('invalid_source_sticks')
  return {type:'DRAW_AGENT_PRICE_STICKS',id:raw.id,interval:raw.interval,label:raw.label,color:raw.color,
    bar_count:raw.bar_count,start_source:sanitizePriceSource(raw.start_source),
    end_source:sanitizePriceSource(raw.end_source),condition:sanitizePriceCondition(raw.condition),
    start_values:[...raw.start_values],end_values:[...raw.end_values],sticks_hash:raw.sticks_hash,
    ...(raw.row_hash ? {row_hash:raw.row_hash} : {})}
}

export function sticksObservation(raw:any):any {return {sticks_hash:raw.sticks_hash,bar_count:raw.bar_count}}
