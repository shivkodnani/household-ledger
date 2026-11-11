const form=document.querySelector('#login-form');
const errorBox=document.querySelector('#login-error');
const submitButton=document.querySelector('#login-submit');
const passkeyButton=document.querySelector('#passkey-login');
const passkeyLabel=passkeyButton.querySelector('span');
const passkeyIdleLabel=passkeyLabel.textContent;
const passkeyDivider=document.querySelector('.login-divider');
const passkeyNote=document.querySelector('.passkey-login-note');
const themeButton=document.querySelector('#login-theme-toggle');
let csrfToken='';
function syncTheme(){
  const dark=document.documentElement.dataset.theme==='dark';
  themeButton.querySelector('use').setAttribute('href',`/icons.svg#${dark?'sun':'moon'}`);
  themeButton.setAttribute('aria-label',dark?'Switch to light mode':'Switch to dark mode');
  themeButton.title=dark?'Switch to light mode':'Switch to dark mode';
  themeButton.setAttribute('aria-pressed',dark?'true':'false');
  document.querySelector('meta[name="theme-color"]').content=dark?'#09090b':'#f7f8fa';
}
themeButton.addEventListener('click',()=>{
  const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';
  document.documentElement.dataset.theme=theme;
  try{localStorage.setItem('household-ledger-theme',theme)}catch{}
  syncTheme();
});
syncTheme();
function base64urlToBuffer(value){const padded=value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4),binary=atob(padded),bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);return bytes.buffer}
function bufferToBase64url(value){const bytes=new Uint8Array(value);let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')}
function requestOptionsFromJSON(options){options.challenge=base64urlToBuffer(options.challenge);options.allowCredentials=(options.allowCredentials||[]).map(item=>({...item,id:base64urlToBuffer(item.id)}));return options}
function credentialPayload(credential){const response=credential.response;return{id:credential.id,rawId:bufferToBase64url(credential.rawId),type:credential.type,response:{authenticatorData:bufferToBase64url(response.authenticatorData),clientDataJSON:bufferToBase64url(response.clientDataJSON),signature:bufferToBase64url(response.signature),userHandle:response.userHandle?bufferToBase64url(response.userHandle):null},authenticatorAttachment:credential.authenticatorAttachment||null,clientExtensionResults:{}}}
async function postJSON(url,data){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(data),cache:'no-store'});const result=await response.json();if(!response.ok)throw Error(result.error||'Sign-in failed');return result}
async function initialize(){
  if(window.PublicKeyCredential&&navigator.credentials?.get){passkeyButton.hidden=false;passkeyDivider.hidden=false;passkeyNote.hidden=false}else{passkeyButton.hidden=true;passkeyDivider.hidden=true;passkeyNote.hidden=true}
  try{
    const response=await fetch('/api/auth/status',{cache:'no-store'});
    const state=await response.json();
    if(!state.auth_required||state.authenticated){location.replace('/');return}
    csrfToken=state.csrf_token||'';
  }catch{
    errorBox.textContent='Could not connect to the sign-in service. Reload and try again.';
    errorBox.hidden=false;
  }
}
form.addEventListener('submit',async event=>{
  event.preventDefault();
  submitButton.disabled=true;
  errorBox.hidden=true;
  try{
    const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(Object.fromEntries(new FormData(form).entries()))});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Sign-in failed');
    location.replace('/');
  }catch(error){
    errorBox.textContent=error.message;
    errorBox.hidden=false;
    submitButton.disabled=false;
  }
});
passkeyButton.addEventListener('click',async()=>{
  if(!window.PublicKeyCredential||!navigator.credentials?.get)return;
  passkeyButton.disabled=true;
  passkeyButton.classList.add('is-busy');
  passkeyButton.setAttribute('aria-busy','true');
  passkeyLabel.textContent='Waiting for your device…';
  submitButton.disabled=true;
  errorBox.hidden=true;
  try{
    const options=await postJSON('/api/auth/passkey/login/options',{});
    const credential=await navigator.credentials.get({publicKey:requestOptionsFromJSON(options.public_key)});
    if(!credential)throw Error('Passkey sign-in was cancelled.');
    passkeyLabel.textContent='Checking your passkey…';
    await postJSON('/api/auth/passkey/login/verify',{challenge_id:options.challenge_id,credential:credentialPayload(credential)});
    passkeyLabel.textContent='Opening your ledger…';
    location.replace('/');
  }catch(error){
    errorBox.textContent=error.name==='NotAllowedError'?'Passkey sign-in was cancelled or timed out.':error.message;
    errorBox.hidden=false;
    passkeyButton.disabled=false;
    passkeyButton.classList.remove('is-busy');
    passkeyButton.setAttribute('aria-busy','false');
    passkeyLabel.textContent=passkeyIdleLabel;
    submitButton.disabled=false;
  }
});
initialize();
