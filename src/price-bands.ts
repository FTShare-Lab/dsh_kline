import { sanitizePriceSource, sanitizePriceCondition } from './price-series.ts'

const COLORS=new Set(['info','warning','success','danger'])
const INTERVALS=new Set(['minute','day','week','month','quarter','year'])

function bandSource(raw:any,output:'upperband'|'lowerband'):any {
  if(raw?.kind!=='bbands')return sanitizePriceSource(raw)
  if(!raw || typeof raw!=='object' || Array.isArray(raw) || Object.keys(raw).length!==6
    || raw.output!==output || !Number.isSafeInteger(raw.period) || raw.period<2 || raw.period>200
    || typeof raw.deviation_up!=='number' || !Number.isFinite(raw.deviation_up)
    || raw.deviation_up<=0 || raw.deviation_up>5
    || typeof raw.deviation_down!=='number' || !Number.isFinite(raw.deviation_down)
    || raw.deviation_down<=0 || raw.deviation_down>5 || raw.matype!==0)throw Error('invalid_source_band')
  return {kind:'bbands',output,period:raw.period,deviation_up:raw.deviation_up,
    deviation_down:raw.deviation_down,matype:0}
}

/** One bounded object; null pairs are explicit gaps and crossed bounds are refused. */
export function sanitizePriceBandCommand(raw:any,expectedBars:number,interval:string):any {
  if(raw?.type!=='DRAW_AGENT_PRICE_BAND' || typeof raw.id!=='string' || !/^band_[a-f0-9]{24}$/.test(raw.id)
    || !INTERVALS.has(raw.interval) || !COLORS.has(raw.color) || typeof raw.label!=='string' || raw.label.length>48
    || !/^[a-f0-9]{64}$/.test(raw.band_hash) || raw.row_hash!=null && !/^[a-f0-9]{16}$/.test(raw.row_hash)
    || !Number.isSafeInteger(raw.bar_count)
    || raw.bar_count<1 || raw.bar_count>4000 || raw.interval===interval && raw.bar_count!==expectedBars
    || !Array.isArray(raw.upper_values) || !Array.isArray(raw.lower_values)
    || raw.upper_values.length!==raw.bar_count || raw.lower_values.length!==raw.bar_count)throw Error('invalid_source_band')
  const upperSource=bandSource(raw.upper_source,'upperband')
  const lowerSource=bandSource(raw.lower_source,'lowerband')
  const boll=upperSource.kind==='bbands'
  if(boll!==(lowerSource.kind==='bbands') || boll && (
    raw.condition!=null || JSON.stringify({...upperSource,output:null})!==JSON.stringify({...lowerSource,output:null})
    || !Array.isArray(raw.middle_values) || raw.middle_values.length!==raw.bar_count)
    || !boll && raw.middle_values!==undefined)throw Error('invalid_source_band')
  let present=0
  for(let i=0;i<raw.bar_count;i++) {
    const upper=raw.upper_values[i],lower=raw.lower_values[i]
    const middle=boll ? raw.middle_values[i] : null
    if(upper===null && lower===null && middle===null)continue
    if(typeof upper!=='number' || typeof lower!=='number' || !Number.isFinite(upper) || !Number.isFinite(lower)
      || lower<=0 || upper<=lower || boll && (typeof middle!=='number' || !Number.isFinite(middle)
        || !(lower<middle && middle<upper)))throw Error('invalid_source_band')
    present++
  }
  if(!present)throw Error('invalid_source_band')
  return {type:'DRAW_AGENT_PRICE_BAND',id:raw.id,interval:raw.interval,label:raw.label,color:raw.color,
    bar_count:raw.bar_count,upper_source:upperSource,
    lower_source:lowerSource,condition:sanitizePriceCondition(raw.condition),
    upper_values:[...raw.upper_values],lower_values:[...raw.lower_values],band_hash:raw.band_hash,
    ...(boll ? {middle_values:[...raw.middle_values]} : {}),
    ...(raw.row_hash ? {row_hash:raw.row_hash} : {})}
}

export function bandObservation(raw:any):any {return {band_hash:raw.band_hash,bar_count:raw.bar_count}}
