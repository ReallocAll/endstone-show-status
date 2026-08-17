"use strict";

const I18N = {
  "zh-CN": {
    publicStatus:"公开服务器状态", connecting:"正在连接", connectionLost:"状态连接中断", retrying:"页面会自动重试，游戏服务器不一定已离线。",
    players:"玩家", onlineNow:"当前在线", serverState:"服务器状态", lastFiveMinutes:"最近五分钟", tickPerformance:"Tick 性能",
    hostAndProcess:"主机与进程", resourceUsage:"资源占用", memory:"内存", bdsCpu:"BDS CPU", multiCoreNote:"100% 约等于一个核心",
    bdsMemory:"BDS 内存", hostMemory:"主机内存", network:"主机网络", disk:"磁盘", uptime:"运行时长", bdsProcess:"BDS 进程",
    adventurers:"冒险者", onlinePlayers:"在线玩家", loadingPlayers:"正在读取玩家列表…", serverChat:"服务器聊天", recentMessages:"最近消息",
    loadingChat:"正在读取聊天…", lastUpdated:"最后更新", minecraftVersion:"Minecraft", webProtection:"网页防护", smooth:"流畅", busy:"繁忙",
    lagging:"卡顿", offline:"不可用", noPlayers:"当前没有玩家在线", noChat:"最近没有聊天消息", hidden:"未公开", copied:"服务器地址已复制",
    protected:"已启用", stale:"数据已过期", good:"正常", high:"偏高", full:"已满", incoming:"下行", outgoing:"上行", perSecond:"/秒"
  },
  "en-US": {
    publicStatus:"PUBLIC SERVER STATUS", connecting:"Connecting", connectionLost:"Status connection lost", retrying:"The page will retry automatically; the game server may still be online.",
    players:"Players", onlineNow:"Online now", serverState:"Server state", lastFiveMinutes:"LAST FIVE MINUTES", tickPerformance:"Tick performance",
    hostAndProcess:"HOST AND PROCESS", resourceUsage:"Resource usage", memory:"Memory", bdsCpu:"BDS CPU", multiCoreNote:"100% is about one CPU core",
    bdsMemory:"BDS memory", hostMemory:"Host memory", network:"Host network", disk:"Disk", uptime:"Uptime", bdsProcess:"BDS process",
    adventurers:"ADVENTURERS", onlinePlayers:"Online players", loadingPlayers:"Loading players…", serverChat:"SERVER CHAT", recentMessages:"Recent messages",
    loadingChat:"Loading chat…", lastUpdated:"Last updated", minecraftVersion:"Minecraft", webProtection:"Web protection", smooth:"Smooth", busy:"Busy",
    lagging:"Lagging", offline:"Unavailable", noPlayers:"No players are online", noChat:"No recent chat messages", hidden:"Not public", copied:"Server address copied",
    protected:"Enabled", stale:"Data is stale", good:"Normal", high:"High", full:"Full", incoming:"Down", outgoing:"Up", perSecond:"/s"
  }
};

const $ = id => document.getElementById(id);
const nodes = Object.fromEntries([
  "serverName","onlineBadge","addressButton","serverAddress","themeButton","languageButton","connectionBanner","tpsValue","tpsHint","tpsMeter",
  "msptValue","msptHint","msptMeter","playersValue","playersMeter","healthValue","healthHint","healthMeter","processCpu","processMemory","hostMemory",
  "hostMemoryDetail","networkRate","networkDetail","diskUsage","diskDetail","uptime","playerCountChip","playerList","chatList","lastUpdated",
  "minecraftVersion","endstoneVersion","webProtection","toast","tickChart","resourceChart"
].map(id => [id,$(id)]));

let language = localStorage.getItem("show-status-language") || "zh-CN";
let statusData = null;
let historyData = null;
let consecutiveErrors = 0;
let statusTimer = null;
let historyTimer = null;
const cache = new Map();

function t(key) { return (I18N[language] || I18N["zh-CN"])[key] || key; }
function applyLanguage() {
  document.documentElement.lang = language;
  document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n); });
  nodes.languageButton.textContent = language === "zh-CN" ? "EN" : "中";
  if (statusData) renderStatus(statusData);
  if (historyData) drawCharts();
}

function setTheme(theme) {
  const value = theme === "grass" ? "grass" : "deepslate";
  document.documentElement.dataset.theme = value;
  localStorage.setItem("show-status-theme", value);
  nodes.themeButton.textContent = value === "grass" ? "☾" : "☀";
  requestAnimationFrame(drawCharts);
}

function formatBytes(value) {
  const n = Number(value || 0);
  const units = ["B","KB","MB","GB","TB"];
  let index = 0, current = n;
  while (current >= 1024 && index < units.length - 1) { current /= 1024; index++; }
  const digits = index >= 3 ? 1 : 0;
  return `${current.toFixed(digits)} ${units[index]}`;
}
function formatRate(value) { return `${formatBytes(value)}${t("perSecond")}`; }
function formatDuration(seconds) {
  seconds = Math.max(0, Math.floor(Number(seconds || 0)));
  const days = Math.floor(seconds / 86400); seconds %= 86400;
  const hours = Math.floor(seconds / 3600); seconds %= 3600;
  const minutes = Math.floor(seconds / 60);
  if (language === "zh-CN") return days ? `${days}天 ${hours}小时` : hours ? `${hours}小时 ${minutes}分` : `${minutes}分`;
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}
function formatClock(ms) {
  if (!ms) return "--";
  return new Intl.DateTimeFormat(language, {hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(new Date(ms));
}
function clamp(value,min,max){ return Math.min(max,Math.max(min,value)); }
function gradeLabel(code) { return code === "smooth" ? t("smooth") : code === "busy" ? t("busy") : code === "lagging" ? t("lagging") : t("offline"); }
function gradeClass(code) { return code === "busy" ? "grade-warning" : code === "lagging" || code === "offline" ? "grade-critical" : "grade-good"; }
function setCardGrade(metric, code) {
  const card = document.querySelector(`[data-metric="${metric}"]`);
  if (!card) return;
  card.classList.remove("grade-good","grade-warning","grade-critical");
  card.classList.add(gradeClass(code));
}
function pingClass(ping) { return ping >= 180 ? "critical" : ping >= 100 ? "warning" : ""; }

async function fetchCached(url, timeoutMs = 4500) {
  const previous = cache.get(url);
  const headers = previous?.etag ? {"If-None-Match":previous.etag} : {};
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {cache:"no-cache",headers,signal:controller.signal});
    if (response.status === 304 && previous) return previous.data;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    cache.set(url,{etag:response.headers.get("ETag"),data});
    return data;
  } finally { clearTimeout(timeout); }
}

async function refreshStatus() {
  clearTimeout(statusTimer);
  try {
    const data = await fetchCached("/api/v1/status");
    statusData = data;
    consecutiveErrors = 0;
    nodes.connectionBanner.hidden = true;
    renderStatus(data);
  } catch (_) {
    consecutiveErrors++;
    nodes.connectionBanner.hidden = false;
    renderOffline();
  } finally {
    const base = document.hidden ? 10000 : 1000;
    const backoff = Math.min(15000, base * Math.pow(1.7, Math.min(consecutiveErrors,5)));
    statusTimer = setTimeout(refreshStatus, backoff + Math.floor(Math.random()*180));
  }
}

async function refreshHistory() {
  clearTimeout(historyTimer);
  try {
    historyData = await fetchCached("/api/v1/history", 6000);
    drawCharts();
  } catch (_) { /* current status remains useful */ }
  finally { historyTimer = setTimeout(refreshHistory, document.hidden ? 20000 : 5000); }
}

function renderOffline() {
  nodes.onlineBadge.className = "status-badge status-offline";
  nodes.onlineBadge.lastElementChild.textContent = t("offline");
  nodes.healthValue.textContent = t("offline");
  nodes.healthHint.textContent = t("connectionLost");
  setCardGrade("health","offline");
}

function renderStatus(data) {
  const server = data.server || {};
  const process = data.process || {};
  const system = data.system || {};
  const ui = data.ui || {};
  const web = data.web || {};
  const stale = Date.now() - Number(data.generated_at_ms || 0) > Number(data.stale_after_ms || 5000);
  const health = stale ? "busy" : (server.health || "offline");

  if (!localStorage.getItem("show-status-language") && ui.language && language !== ui.language) { language = ui.language; applyLanguage(); return; }
  if (!localStorage.getItem("show-status-theme") && ui.default_theme) setTheme(ui.default_theme);
  document.title = `${ui.server_name || "Bedrock Server"} · ${gradeLabel(health)}`;
  nodes.serverName.textContent = ui.server_name || "Bedrock Server";
  nodes.serverAddress.textContent = ui.server_address || "";
  nodes.addressButton.hidden = !ui.server_address;

  nodes.onlineBadge.className = `status-badge ${health === "smooth" ? "status-online" : health === "busy" ? "status-warning" : "status-offline"}`;
  nodes.onlineBadge.lastElementChild.textContent = stale ? t("stale") : gradeLabel(health);

  const tps = Number(server.tps || 0), mspt = Number(server.mspt || 0), tickUsage = Number(server.tick_usage || 0);
  nodes.tpsValue.textContent = tps.toFixed(1);
  nodes.tpsHint.textContent = `${(tickUsage*100).toFixed(1)}%`;
  nodes.tpsMeter.style.width = `${clamp(tps/20*100,0,100)}%`;
  setCardGrade("tps", tps >= 19.5 ? "smooth" : tps >= 18 ? "busy" : "lagging");

  nodes.msptValue.textContent = `${mspt.toFixed(1)} ms`;
  nodes.msptHint.textContent = mspt <= 40 ? t("good") : t("high");
  nodes.msptMeter.style.width = `${clamp(mspt/50*100,0,100)}%`;
  setCardGrade("mspt", mspt <= 40 ? "smooth" : mspt <= 50 ? "busy" : "lagging");

  const online = Number(server.players_online || 0), maximum = Number(server.players_max || 0);
  nodes.playersValue.textContent = maximum > 0 ? `${online} / ${maximum}` : String(online);
  nodes.playersMeter.style.width = `${maximum > 0 ? clamp(online/maximum*100,0,100) : clamp(online*5,0,100)}%`;
  setCardGrade("players", maximum > 0 && online >= maximum ? "busy" : "smooth");

  nodes.healthValue.textContent = gradeLabel(health);
  nodes.healthHint.textContent = stale ? t("stale") : `${tps.toFixed(1)} TPS`;
  nodes.healthMeter.style.width = health === "smooth" ? "100%" : health === "busy" ? "66%" : "28%";
  setCardGrade("health",health);

  nodes.processCpu.textContent = `${Number(process.cpu_percent || 0).toFixed(1)}%`;
  nodes.processMemory.textContent = formatBytes(process.rss_bytes);
  nodes.hostMemory.textContent = `${Number(system.memory_percent || 0).toFixed(1)}%`;
  nodes.hostMemoryDetail.textContent = `${formatBytes(system.memory_used_bytes)} / ${formatBytes(system.memory_total_bytes)}`;
  nodes.networkRate.textContent = `↓ ${formatRate(system.network_receive_bytes_per_second)}`;
  nodes.networkDetail.textContent = `↑ ${formatRate(system.network_send_bytes_per_second)}`;
  nodes.diskUsage.textContent = `${Number(system.disk_percent || 0).toFixed(1)}%`;
  nodes.diskDetail.textContent = `${formatBytes(system.disk_used_bytes)} / ${formatBytes(system.disk_total_bytes)}`;
  nodes.uptime.textContent = formatDuration(server.uptime_seconds);
  nodes.lastUpdated.textContent = formatClock(data.generated_at_ms);
  nodes.minecraftVersion.textContent = server.minecraft_version || "--";
  nodes.endstoneVersion.textContent = server.endstone_version || "--";
  nodes.webProtection.textContent = `${t("protected")} · ${Number(web.rejected_requests || 0)}`;

  renderPlayers(data.players, data.features?.players);
  renderChat(data.chat, data.features?.chat);
}

function renderPlayers(players, exposed) {
  nodes.playerList.replaceChildren();
  const list = Array.isArray(players) ? players : [];
  nodes.playerCountChip.textContent = String(list.length);
  if (!exposed) return nodes.playerList.append(empty(t("hidden")));
  if (!list.length) return nodes.playerList.append(empty(t("noPlayers")));
  const fragment = document.createDocumentFragment();
  for (const player of list) {
    const row = document.createElement("div"); row.className = "player-row";
    const head = document.createElement("span"); head.className = "mini-head"; head.setAttribute("aria-hidden","true");
    const name = document.createElement("span"); name.className = "player-name"; name.textContent = player.name || "?";
    const ping = document.createElement("span"); ping.className = `ping ${pingClass(Number(player.ping || 0))}`; ping.textContent = `${Number(player.ping || 0)} ms`;
    row.append(head,name,ping); fragment.append(row);
  }
  nodes.playerList.append(fragment);
}

function renderChat(messages, exposed) {
  const nearBottom = nodes.chatList.scrollHeight - nodes.chatList.scrollTop - nodes.chatList.clientHeight < 45;
  nodes.chatList.replaceChildren();
  const list = Array.isArray(messages) ? messages : [];
  if (!exposed) return nodes.chatList.append(empty(t("hidden")));
  if (!list.length) return nodes.chatList.append(empty(t("noChat")));
  const fragment = document.createDocumentFragment();
  for (const item of list) {
    const row = document.createElement("div"); row.className = "chat-row";
    const time = document.createElement("span"); time.className = "chat-time"; time.textContent = formatClock(item.time_ms);
    const player = document.createElement("span"); player.className = "chat-player"; player.textContent = `<${item.player || "?"}>`;
    const message = document.createElement("span"); message.className = "chat-message"; message.textContent = item.message || "";
    row.append(time,player,message); fragment.append(row);
  }
  nodes.chatList.append(fragment);
  if (nearBottom) nodes.chatList.scrollTop = nodes.chatList.scrollHeight;
}
function empty(text) { const node=document.createElement("p"); node.className="empty-state"; node.textContent=text; return node; }

function drawCharts() {
  const points = historyData?.points || [];
  drawChart(nodes.tickChart, points, [
    {key:"tps", color:"#55c85a", transform:v=>v},
    {key:"mspt", color:"#f2c94c", transform:v=>v/3}
  ], [0,5,10,15,20]);
  drawChart(nodes.resourceChart, points, [
    {key:"process_cpu_total_percent", color:"#5bb7e8", transform:v=>v},
    {key:"memory_percent", color:"#b48be0", transform:v=>v}
  ], [0,25,50,75,100]);
}

function drawChart(canvas, points, series, labels) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 10 || rect.height < 10) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.floor(rect.width*dpr); canvas.height = Math.floor(rect.height*dpr);
  const ctx = canvas.getContext("2d"); ctx.scale(dpr,dpr); ctx.imageSmoothingEnabled=false;
  const width=rect.width,height=rect.height,pad={l:34,r:10,t:12,b:22},cw=width-pad.l-pad.r,ch=height-pad.t-pad.b;
  const styles=getComputedStyle(document.documentElement); const muted=styles.getPropertyValue("--muted").trim()||"#aaa";
  ctx.clearRect(0,0,width,height); ctx.font="10px monospace"; ctx.textAlign="right"; ctx.textBaseline="middle";
  labels.forEach((label,index)=>{ const y=pad.t+ch-(index/(labels.length-1))*ch; ctx.strokeStyle="rgba(255,255,255,.09)"; ctx.lineWidth=1; ctx.beginPath(); ctx.moveTo(pad.l,y+.5); ctx.lineTo(width-pad.r,y+.5); ctx.stroke(); ctx.fillStyle=muted; ctx.fillText(String(label),pad.l-6,y); });
  if (!points.length) { ctx.fillStyle=muted; ctx.textAlign="center"; ctx.fillText("…",pad.l+cw/2,pad.t+ch/2); return; }
  const axisMax = Number(labels.at(-1) || 100);
  series.forEach(item=>{
    ctx.strokeStyle=item.color; ctx.lineWidth=2; ctx.beginPath();
    points.forEach((point,index)=>{ const x=pad.l+(points.length===1?cw:index/(points.length-1)*cw); const value=clamp(item.transform(Number(point[item.key]||0)),0,axisMax); const y=pad.t+ch-(value/axisMax)*ch; if(index===0)ctx.moveTo(x,y);else{ctx.lineTo(x,y);} });
    ctx.stroke();
  });
  ctx.fillStyle=muted; ctx.textAlign="left"; ctx.textBaseline="bottom"; ctx.fillText(formatClock(points[0]?.time_ms),pad.l,height-3); ctx.textAlign="right"; ctx.fillText(formatClock(points.at(-1)?.time_ms),width-pad.r,height-3);
}

function showToast(message) {
  nodes.toast.textContent = message; nodes.toast.hidden = false;
  clearTimeout(showToast.timer); showToast.timer = setTimeout(()=>{nodes.toast.hidden=true;},1800);
}

nodes.themeButton.addEventListener("click",()=>setTheme(document.documentElement.dataset.theme === "deepslate" ? "grass" : "deepslate"));
nodes.languageButton.addEventListener("click",()=>{ language = language === "zh-CN" ? "en-US" : "zh-CN"; localStorage.setItem("show-status-language",language); applyLanguage(); });
nodes.addressButton.addEventListener("click",async()=>{ try { await navigator.clipboard.writeText(nodes.serverAddress.textContent); showToast(t("copied")); } catch (_) {} });
document.addEventListener("visibilitychange",()=>{ clearTimeout(statusTimer); clearTimeout(historyTimer); refreshStatus(); refreshHistory(); });
window.addEventListener("resize",()=>requestAnimationFrame(drawCharts));

setTheme(localStorage.getItem("show-status-theme") || "deepslate");
applyLanguage();
refreshStatus();
refreshHistory();
