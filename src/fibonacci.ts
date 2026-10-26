/** Validate price-domain geometry and produce exact overlay points, never pixels. */
export function fibonacciOverlayPoints(c: any): { timestamp: number; value: number }[] {
  const validPoint=(p:any)=>Number.isSafeInteger(p?.time) && p.time>0 && typeof p.price==='number' && Number.isFinite(p.price) && p.price>0
  if(c?.geometry_basis!=='linear_price_retracement' || !validPoint(c.from) || !validPoint(c.to)
    || c.from.time>=c.to.time || c.from.price===c.to.price || !Array.isArray(c.ratios) || !c.ratios.length || c.ratios.length>16
    || !Array.isArray(c.levels) || c.levels.length!==c.ratios.length)throw Error('invalid_fibonacci_geometry')
  const points=[c.from,c.to].map(p=>({timestamp:p.time*1000,value:p.price}))
  c.ratios.forEach((r:any,i:number)=>{
    const level=c.levels[i], expected=c.to.price-r*(c.to.price-c.from.price)
    if(typeof r!=='number' || !Number.isFinite(r) || r<0 || r>1 || i>0 && r<=c.ratios[i-1]
      || level?.ratio!==r || typeof level.price!=='number' || !Number.isFinite(level.price) || level.price<=0
      || Math.abs(level.price-expected)>Math.max(1,Math.abs(expected))*1e-12)throw Error('invalid_fibonacci_geometry')
    points.push({timestamp:c.from.time*1000,value:level.price},{timestamp:c.to.time*1000,value:level.price})
  })
  return points
}
