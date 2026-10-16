/** Synchronous local-state guard; receipts are not proof of screen pixels. */
import { drawingInventory, observationKey } from '../chart-observation.ts'
import { sanitizeDrawingFeedback } from '../drawing-feedback.ts'
interface Options {
  conversationId?:string; viewId:string; capture:()=>any; isActive:()=>boolean
  apply:(payload:any,token:string)=>any; confirm?:(token:string)=>void
}
const TOKEN=/^[A-Za-z0-9_-]{32}$/
export function createChartApplyController(options:Options) {
  const seen=new Map<string,any>()
  let applying=false
  return {
    consume(command:any,publication:any) {
      const token=command?.candidate_chart_session, lease=command?.lease_id
      if(typeof token!=='string' || !TOKEN.test(token) || typeof lease!=='string' || !TOKEN.test(lease))return undefined
      const previous=seen.get(token)
      if(previous) return previous.lease_id===lease ? previous : undefined
      const receipt:any={candidate_chart_session:token,lease_id:lease,status:'rejected',reason:'invalid_delivery'}
      seen.set(token,receipt)
      if(seen.size>64 || applying || !options.conversationId || command.conversation_id!==options.conversationId
        || command.view_id!==options.viewId || command.context_ref!==publication.context_ref
        || command.expected_revision!==publication.revision || !Number.isSafeInteger(command.expires_at_ms)
        || command.expires_at_ms<Date.now())return receipt
      if(!options.isActive()) {receipt.reason='inactive';return receipt}
      try {
        if(observationKey(options.capture())!==observationKey(command.base_state)) {receipt.reason='local_state_changed';return receipt}
        applying=true
        const result:any=options.apply(command.payload,token)
        if(result?.then)throw Error('async_apply_not_supported')
        const allowed=[...new Map([...command.base_state.drawings.filter((d:any)=>d.origin==='ai'),
          ...drawingInventory(command.payload)].map((d:any)=>[d.id,d])).values()]
        receipt.drawing_feedback=sanitizeDrawingFeedback(result,allowed)
        const expected={...command.base_state,source_chart_session:token,
          drawings:[...command.base_state.drawings.filter((d:any)=>d.origin!=='ai'),...drawingInventory(command.payload)]}
        if(observationKey(options.capture())!==observationKey(expected)) {
          receipt.status='outcome_unknown';receipt.reason='apply_failed'
        } else {receipt.status='applied';delete receipt.reason}
      } catch(error:any) {
        receipt.status=error?.rolledBack===true ? 'failed' : 'outcome_unknown'
        receipt.reason=error?.rolledBack===true ? 'apply_failed' : 'rollback_failed'
        const allowed=[...new Map([...command.base_state.drawings.filter((d:any)=>d.origin==='ai'),
          ...drawingInventory(command.payload)].map((d:any)=>[d.id,d])).values()]
        receipt.drawing_feedback=sanitizeDrawingFeedback(error?.drawing_feedback,allowed)
      } finally {applying=false}
      return receipt
    },
    confirm(ack:any) {
      const local=seen.get(ack?.candidate_chart_session)
      if(!local || local.lease_id!==ack.lease_id || ack.apply_status!=='applied' || local.status!=='applied'
        || ack.confirmed_chart_session!==ack.candidate_chart_session)return
      if(!local.confirmed) {options.confirm?.(ack.candidate_chart_session);local.confirmed=true}
    },
  }
}
