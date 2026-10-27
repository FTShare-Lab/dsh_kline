/** Non-authorizing row identity for candle-index-aligned drawings. */
export function candleSequenceHash(rows:any[]):string {
  const bytes=new DataView(new ArrayBuffer(8))
  let hash=0xcbf29ce484222325n
  for(const row of rows)for(const key of ['time','open','high','low','close','volume']) {
    const value=row?.[key]
    if(typeof value!=='number' || !Number.isFinite(value))throw Error('invalid_candle_sequence')
    bytes.setFloat64(0,value,false)
    for(let i=0;i<8;i++)hash=BigInt.asUintN(64,(hash^BigInt(bytes.getUint8(i)))*0x100000001b3n)
  }
  return hash.toString(16).padStart(16,'0')
}
