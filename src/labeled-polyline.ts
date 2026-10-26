/** Canonical explicit labeled paths: no sorting, snapping or automatic waves. */
export interface LabeledPolylinePoint { label: string; time: number; price: number }
export function sanitizePolylinePoints(raw: any): LabeledPolylinePoint[] {
  if(!Array.isArray(raw) || raw.length<2 || raw.length>8)throw Error('invalid_polyline_points')
  const seen=new Set<string>()
  return raw.map((p:any,i:number)=>{
    if(typeof p?.label!=='string' || !p.label.length || [...p.label].length>16 || p.label!==p.label.trim()
      || /[\x00-\x1f]/.test(p.label) || seen.has(p.label) || !Number.isSafeInteger(p.time) || p.time<=0
      || typeof p.price!=='number' || !Number.isFinite(p.price) || p.price<=0
      || i>0 && p.time<=raw[i-1].time)throw Error('invalid_polyline_points')
    seen.add(p.label)
    return {label:p.label,time:p.time,price:p.price}
  })
}
export function polylineOverlayPoints(command: any): { timestamp: number; value: number }[] {
  return sanitizePolylinePoints(command.points).map(p=>({timestamp:p.time*1000,value:p.price}))
}
