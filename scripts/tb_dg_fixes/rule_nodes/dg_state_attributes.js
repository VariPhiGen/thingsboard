// Debounce state computed by 'Compute DG Status' -> server attributes for the next message
return {
  msg: {
    dg_state_confirmed: metadata.dg_state_confirmed,
    dg_state_candidate: metadata.dg_state_candidate,
    dg_state_candidate_ts: Number(metadata.dg_state_candidate_ts)
  },
  metadata: metadata,
  msgType: 'POST_ATTRIBUTES_REQUEST'
};
