// The DG controller kWh counter arrives 10x too high (verified against integrated power_kw and
// run_hours on every DG since July 2026). Devices with server attribute energy_kwh_scale get
// energy_kwh multiplied by it; the controller value is kept as energy_kwh_raw. When the gateway
// itself is fixed, set energy_kwh_scale to 1 (or delete it) so the value is not scaled twice.
var scale = Number(metadata.ss_energy_kwh_scale);
if (metadata.ss_energy_kwh_scale === undefined || metadata.ss_energy_kwh_scale === '' ||
    !isFinite(scale) || scale <= 0 || scale === 1) {
  return {msg: msg, metadata: metadata, msgType: msgType};
}
var v = msg.energy_kwh;
var n = (v === null || v === '' || typeof v === 'boolean') ? NaN : Number(v);
msg.energy_kwh_raw = v;
// Text such as 'error' and the sensor-offline codes stay as they are so they are still recognised
if (isFinite(n) && n !== 32767 && n !== 65535) {
  msg.energy_kwh = Math.round(n * scale * 1000) / 1000;
}
return {msg: msg, metadata: metadata, msgType: msgType};
