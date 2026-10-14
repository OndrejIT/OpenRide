// First-time setup page, served by the ESP32 on its own Wi-Fi (and at / in normal mode, to change the trainer).
#pragma once
#include <Arduino.h>

static const char SETUP_PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenRide most – nastavení</title>
<style>
:root{color-scheme:light dark;--bg:#fcfcfb;--card:#f3f2ef;--line:#d9d8d2;--text:#0b0b0b;--muted:#6b6a65;--accent:#eb6834;--bad:#c53030;--good:#2f855a}
@media (prefers-color-scheme:dark){:root{--bg:#0e0e0d;--card:#1a1a19;--line:#3a3a37;--text:#f0efec;--muted:#a3a29c;--bad:#f56565;--good:#48bb78}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,sans-serif}
main{max-width:520px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:0 0 10px}
p{margin:6px 0}.muted{color:var(--muted)}section{background:var(--card);border-radius:10px;padding:14px;margin:14px 0}
label{display:block;margin:8px 0 4px;font-size:13px;color:var(--muted)}
input,select{width:100%;font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text)}
button{font:inherit;font-weight:600;padding:8px 14px;border:0;border-radius:6px;background:var(--accent);color:#fff;margin-top:10px;cursor:pointer}
button:disabled{opacity:.45}ul{list-style:none;padding:0;margin:8px 0}li{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--line)}
li button{margin:0;padding:4px 10px}.bad{color:var(--bad)}.good{color:var(--good)}
</style></head><body><main>
<h1>OpenRide most</h1><p class="muted">ESP32 mezi trenažérem Kettler a aplikací OpenRide.</p>
<section><h2>1. Wi-Fi</h2><p id="wifiState" class="muted">…</p>
<label for="ssid">Síť</label><select id="ssid"><option value="">načítám sítě…</option></select>
<label for="pass">Heslo</label><input id="pass" type="password" autocomplete="off">
<button id="wifiSave">Připojit</button> <button id="wifiRescan" type="button">Znovu vyhledat sítě</button>
<p id="wifiMsg"></p></section>
<section><h2>2. Trenažér Kettler</h2><p id="kState" class="muted">…</p>
<button id="kScan">Vyhledat Bluetooth zařízení</button><ul id="kList"></ul><p id="kMsg"></p></section>
<p class="muted">Nastavení se pamatuje. Smazat ho jde v OpenRide (Trenažér → Zapomenout) nebo podržením tlačítka BOOT na 5 s.</p>
</main><script>
const $=id=>document.getElementById(id);
// names come from nearby devices and networks: never trust them as HTML
const esc=t=>String(t??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}).then(r=>r.json());
async function status(){
  const s=await fetch('/api/status').then(r=>r.json());
  const w=s.wifi;
  $('wifiState').innerHTML=w.connected?`<span class="good">Připojeno k ${esc(w.ssid)}</span> – adresa <b>http://${w.ip}</b> nebo <b>http://nakole.local</b>`:(w.ssid?`Připojuji k ${esc(w.ssid)}…`:'Zatím nenastaveno.');
  const k=s.kettler;
  $('kState').innerHTML=k.mac?`${k.connected?'<span class="good">Připojeno</span>':'Nepřipojeno'}: ${esc(k.name)} (${esc(k.mac)})`:'Zatím nevybrán.';
  if(k.scanning){$('kScan').disabled=true;$('kMsg').textContent='Vyhledávám (~10 s)…'}
  else if($('kScan').disabled){$('kScan').disabled=false;$('kMsg').textContent='';showDevices(k.devices)}
  return s;
}
function showDevices(list){
  $('kList').innerHTML='';
  if(!list.length){$('kMsg').textContent='Nic nenalezeno. Je Kettler zapnutý?';return}
  for(const d of list){
    const li=document.createElement('li');
    li.innerHTML=`<span>${d.kettler?'<b>':''}${esc(d.name)||'(bez názvu)'}${d.kettler?'</b>':''}<br><span class="muted">${esc(d.mac)} · ${d.rssi} dBm</span></span>`;
    const b=document.createElement('button');b.textContent='Vybrat';
    b.onclick=async()=>{await post('/api/kettler',{mac:d.mac,name:d.name});$('kMsg').textContent='Uloženo, připojuji…';status()};
    li.appendChild(b);$('kList').appendChild(li);
  }
}
async function networks(){
  $('ssid').innerHTML='<option value="">hledám sítě…</option>';
  const list=await fetch('/api/wifi/scan').then(r=>r.json());
  $('ssid').innerHTML=list.map(n=>`<option value="${esc(n.ssid)}">${esc(n.ssid)} (${n.rssi} dBm${n.open?', otevřená':''})</option>`).join('')||'<option value="">žádná síť</option>';
}
$('wifiRescan').onclick=networks;
$('wifiSave').onclick=async()=>{
  $('wifiMsg').textContent='Připojuji…';
  const r=await post('/api/wifi',{ssid:$('ssid').value,password:$('pass').value});
  $('wifiMsg').innerHTML=r.ok?`<span class="good">Připojeno, adresa http://${r.ip}</span>. Za chvíli se most restartuje do běžného režimu a tato síť zmizí; pak ho najdeš na <b>http://nakole.local</b>.`:`<span class="bad">${esc(r.error)}</span>`;
};
$('kScan').onclick=async()=>{await post('/api/kettler/scan');status()};
networks();status();setInterval(status,2000);
</script></body></html>)HTML";
