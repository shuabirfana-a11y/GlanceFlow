const $ = (id) => document.getElementById(id);
let sessionId = null;
let busy = false;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function render(data) {
  if (!data) return;
  const {session, hud, agent_debug: agent} = data;
  sessionId = session.session_id;
  $('hud').dataset.severity = hud.severity;
  $('hudStatus').textContent = hud.status;
  $('hudHeadline').textContent = hud.headline;
  $('hudPrimary').textContent = hud.primary_text;
  $('hudSecondary').textContent = hud.secondary_text || '';
  $('hudPrompt').textContent = hud.prompt || '';
  const labels = {STATIONARY:'静止',MOVING:'移动中',UNKNOWN:'未知'};
  $('motionReadout').textContent = labels[session.motion_state] || labels[$('motion').value];
  $('auditList').innerHTML = session.audit_events.slice().reverse().map(e => `<li><b>${escapeHtml(e.action)}</b> · ${escapeHtml(e.message)}</li>`).join('');
  if (agent) {
    $('agentGoal').textContent = agent.goal;
    $('agentState').textContent = agent.state;
    $('agentRisk').textContent = agent.risk_level;
    $('agentAction').textContent = agent.next_action;
    $('agentRationale').textContent = agent.public_rationale;
    $('agentWaiting').textContent = agent.waiting_for.join('；') || '无';
    $('agentRecent').textContent = agent.recent_tool_result ? `${agent.recent_tool_result.action}：${agent.recent_tool_result.message}` : '无';
  }
}

function escapeHtml(value) { const node = document.createElement('span'); node.textContent = value; return node.innerHTML; }
function setBusy(value, message) { busy = value; document.body.classList.toggle('busy', value); if (message) $('message').textContent = message; }

async function newSession() {
  if (sessionId) { try { await api(`/api/sessions/${sessionId}`, {method:'DELETE'}); } catch (_) {} }
  const data = await api('/api/sessions', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({motion_state:$('motion').value})});
  render(data); $('message').textContent = '新会话已就绪。所有内容只保存在本机内存与临时目录。';
}

async function uploadAndArrange(file) {
  if (!file || busy) return;
  setBusy(true, '正在进行短时抽帧、自动选帧与本地 OCR…');
  const form = new FormData(); form.append('video', file, file.name || 'capture.webm'); form.append('command', $('command').value); form.append('confidence','1'); form.append('motion_state',$('motion').value);
  try { render(await api(`/api/sessions/${sessionId}/capture`, {method:'POST',body:form})); $('message').textContent = '短视频原始临时文件已删除，仅保留自动选中的证据帧。'; }
  catch (error) { $('message').textContent = error.message; }
  finally { setBusy(false); }
}

async function cameraCapture() {
  if (busy) return;
  if ($('command').value.replace(/[\s，。！？、,.!?]/g,'') !== '帮我安排') { $('message').textContent = '相机只会在明确的“帮我安排”指令后启动。'; return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { $('message').textContent = '浏览器不支持短时相机采集，请上传短视频。'; return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
    $('preview').srcObject = stream; $('preview').style.display = 'block'; $('emptyView').style.display = 'none'; $('capturePulse').style.display = 'block'; await $('preview').play();
    const recorder = new MediaRecorder(stream); const chunks=[]; recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    const stopped = new Promise(resolve => recorder.onstop=resolve); recorder.start(); setBusy(true,'短时采集中，将自动停止…');
    await new Promise(resolve => setTimeout(resolve, 2800)); recorder.stop(); await stopped;
    const blob = new Blob(chunks,{type:recorder.mimeType||'video/webm'}); setBusy(false); await uploadAndArrange(new File([blob],'capture.webm',{type:blob.type}));
  } catch (error) { $('message').textContent = `相机不可用：${error.message}`; }
  finally { if(stream)stream.getTracks().forEach(track=>track.stop()); $('capturePulse').style.display='none'; $('preview').style.display='none'; $('emptyView').style.display='grid'; setBusy(false); }
}

async function sendVoice() {
  if (busy) return;
  try { render(await api(`/api/sessions/${sessionId}/voice`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:$('command').value,confidence:1,source:'text-fallback',motion_state:$('motion').value})})); $('message').textContent='指令已处理。'; }
  catch(error){ $('message').textContent=error.message; }
}

async function cancelNow() {
  if (!sessionId) return;
  try { render(await api(`/api/sessions/${sessionId}/voice`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:'取消',confidence:1,source:'explicit-cancel-button'})})); $('message').textContent='已请求取消，不会进入日历写入。'; }
  catch(error){ $('message').textContent=error.message; }
}

function listen() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) { $('message').textContent='当前浏览器不支持语音识别，请使用可见文本输入。'; return; }
  const recognition = new SpeechRecognition(); recognition.lang='zh-CN'; recognition.interimResults=false;
  recognition.onresult=e=>{ $('command').value=e.results[0][0].transcript; $('message').textContent='已识别指令，请检查后发送。'; };
  recognition.onerror=()=>{$('message').textContent='没有识别到可靠语音，请使用文本输入。'}; recognition.start();
}

$('file').addEventListener('change',e=>uploadAndArrange(e.target.files[0])); $('camera').addEventListener('click',cameraCapture); $('send').addEventListener('click',sendVoice); $('cancelNow').addEventListener('click',cancelNow); $('speak').addEventListener('click',listen); $('newSession').addEventListener('click',newSession); newSession().catch(e=>$('message').textContent=e.message);
