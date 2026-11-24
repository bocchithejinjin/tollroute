const $ = (id) => document.getElementById(id);
const form = $('form');
const googleMode = form.hasAttribute('data-google-routes');
const storageKey = 'tollroute.last-search.v1';
const endpoints = ['origin', 'dest'];
const presets = form.querySelectorAll('[data-budget]');
let activeRequest;
let result;

const yen = (amount) => amount.toLocaleString('ja-JP') + ' 円';
const mins = (minutes) => {
  const total = Math.round(minutes);
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return hours ? `${hours} 時間 ${rest} 分` : `${rest} 分`;
};
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

// 数字は大きく、単位は小さく見せる（読み上げは通常の文字列と同じ）。
const yenHtml = (amount) => `<span class="num">${amount.toLocaleString('ja-JP')}</span><span class="unit">円</span>`;
const minsHtml = (minutes) => {
  const total = Math.round(minutes);
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  const part = (value, unit) => `<span class="num">${value}</span><span class="unit">${unit}</span>`;
  return hours ? part(hours, '時間') + part(rest, '分') : part(rest, '分');
};

function nowInJapan() {
  return new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 16);
}

function offsetDeparture(depart, offset) {
  const time = Date.parse(depart + 'Z') + offset * 60 * 1000;
  return new Date(time).toISOString().slice(0, 16);
}

function syncPoint(id) {
  const custom = !$(id + '-select').value;
  $(id).hidden = $(id).disabled = !custom;
  $(id).required = custom;
}

function fillPoint(id, value) {
  const select = $(id + '-select');
  select.value = Array.from(select.options).some((option) => option.value === value) ? value : '';
  $(id).value = select.value ? '' : value;
  syncPoint(id);
}

function syncDeparture() {
  const scheduled = form.elements['departure-mode'].value === 'scheduled';
  if (scheduled && !$('depart').value) $('depart').value = nowInJapan();
  $('depart').hidden = $('depart').disabled = !scheduled;
  $('depart').required = scheduled;
}

function syncPresets() {
  presets.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.budget === $('budget').value));
  });
}

function loadPrevious() {
  try {
    const previous = JSON.parse(localStorage.getItem(storageKey));
    if (!previous || typeof previous.origin !== 'string' || !previous.origin.trim()
        || typeof previous.dest !== 'string' || !previous.dest.trim()
        || !/^\d+$/.test(previous.budget)) return;
    endpoints.forEach((id) => fillPoint(id, previous[id]));
    $('budget').value = previous.budget;
    $('forget').hidden = false;
  } catch {
    // Even if local storage is disabled, searching still works.
  }
}

function remember(query) {
  try {
    const {origin, dest, budget} = query;
    localStorage.setItem(storageKey, JSON.stringify({origin, dest, budget}));
    $('forget').hidden = false;
  } catch {
    // Searching does not depend on local storage.
  }
}

function formQuery() {
  const now = form.elements['departure-mode'].value === 'now';
  return {
    origin: $('origin-select').value || $('origin').value.trim(),
    dest: $('dest-select').value || $('dest').value.trim(),
    depart: now ? nowInJapan() : $('depart').value,
    budget: String($('budget').valueAsNumber),
    now,
  };
}

function showTrip(query, data) {
  for (const id of endpoints) {
    const station = Array.from($(id + '-select').options).find((option) => option.value === query[id]);
    $('trip-' + id).textContent = data?.[id].name ?? station?.textContent ?? query[id];
  }
  const [date, time] = query.depart.split('T');
  $('trip-depart').textContent = (query.now ? '出発 ' : date.slice(5).replace('-', '/') + ' ') + time;
  $('trip-budget').textContent = '上限 ' + yen(Number(query.budget));
}

function icPair(plan) {
  return plan.entry ? `${plan.entry} → ${plan.exit}` : '一般道だけ';
}

function selectedTitle(plan, index) {
  if (index === 0) return plan.entry ? '予算内で最速' : '一般道だけで行く';
  return plan.label === 'ほかの候補' ? '選んだルート' : plan.label;
}

const stepKind = (kind) => (kind === 'highway' ? '高速' : '一般道');

// 続いている同じ種類の区間（一般道・高速）をまとめ、道順の流れとして見せる。
function routeFlow(plan) {
  const groups = [];
  for (const step of plan.steps) {
    const last = groups[groups.length - 1];
    if (last && last.kind === step.kind) last.minutes += step.minutes;
    else groups.push({kind: step.kind, minutes: step.minutes});
  }
  return `<ol class="flow" aria-label="道順の流れ">${groups.map((group, index) => `
    <li class="${group.kind === 'highway' ? 'highway' : 'local'}">
      <span class="step-badge" aria-hidden="true">${index + 1}</span>
      <span class="flow-label">${stepKind(group.kind)}<small>約 ${mins(group.minutes)}</small></span>
    </li>`).join('')}</ol>`;
}

function routeDetails(plan) {
  const steps = plan.steps.map((step, index) => (
    `<li class="${step.kind === 'highway' ? 'highway' : 'local'}">
      <span class="step-badge" aria-hidden="true">${index + 1}</span>
      <span class="step-kind">${stepKind(step.kind)}</span>
      <span class="step-text">${esc(step.text)} <span>約 ${mins(step.minutes)}</span></span>
    </li>`
  )).join('');
  const charges = plan.runs.map((run) => (
    `<li><strong>${esc(run.pool)}</strong> ${esc(run.entry)} → ${esc(run.exit)}
      ${run.discount ? `<s>${yen(run.base)}</s> ` : ''}${yen(run.fare)}
      ${run.discount ? `<span>（${esc(run.discount)}）</span>` : ''}</li>`
  )).join('');
  return `<details class="route-details">
    <summary>${charges ? '道順と料金の内訳' : '道順'}</summary>
    <ol>${steps}</ol>
    ${charges ? `<ul>${charges}</ul>` : ''}
  </details>`;
}

function showChosen(index) {
  if (result.google) showGoogleChosen(index);
  else showLocalChosen(index);
  $('choices').querySelectorAll('button').forEach((button) => {
    button.setAttribute('aria-pressed', String(index === Number(button.dataset.choice)));
  });
}

function showLocalChosen(index) {
  const plan = result.plans[index];
  const google = new URL(plan.nav.google);
  if (!plan.entry) google.searchParams.set('avoid', 'tolls,highways');
  const reasons = {
    'いちばんお得': '1 分短縮するのにかかる料金が、予算内でいちばん安い候補です。',
    '安さ重視': '最速ルートで短縮できる時間の半分以上を、いちばん安く短縮できます。',
  };
  const reason = index === 0 && !plan.entry ? 'この予算では、一般道だけで行くのが最速です。' : reasons[plan.label];
  const saving = plan.entry ? (plan.saved > 0 ? `一般道だけより ${mins(plan.saved)}早い` : '一般道だけとほぼ同じ時間') : '';
  $('chosen').innerHTML = `
    <p class="chosen-tag">${index === 0 ? 'おすすめ' : '選択中の候補'}</p>
    <h2 id="chosen-title" tabindex="-1">${esc(selectedTitle(plan, index))}</h2>
    ${reason ? `<p class="chosen-reason">${reason}</p>` : ''}
    <dl class="metrics">
      <div><dt>所要時間</dt><dd class="big">${minsHtml(plan.minutes)}</dd>
        <dd class="sub"><span class="num">${esc(plan.arrive)}</span> 着</dd></div>
      <div><dt>高速代</dt><dd class="big">${yenHtml(plan.fare)}</dd></div>
    </dl>
    ${plan.entry ? `<p class="route-line"><strong>${esc(icPair(plan))}</strong>
      <br>${esc(plan.roads.join('・'))}</p>` : ''}
    ${saving ? `<p class="route-saving">${saving}
      ${plan.yen_per_min != null ? ` · 短縮 1 分あたり ${yen(plan.yen_per_min)}` : ''}</p>` : ''}
    ${routeFlow(plan)}
    <div class="nav-actions">
      <a class="button primary" href="${esc(google.href)}" target="_blank" rel="noopener noreferrer">Google マップで開く</a>
    </div>
    <p class="muted">Google マップで経路を再検索するため、経路や高速代が変わることがあります。</p>
    ${routeDetails(plan)}`;
}

function relativeToFastest(plan, fastest) {
  const minutes = Math.max(0, Math.round(plan.minutes - fastest.minutes));
  const cost = fastest.fare - plan.fare;
  const fareDelta = cost > 0 ? `${yen(cost)}安い` : cost < 0 ? `${yen(-cost)}高い` : '同じ料金';
  return `最速より ${fareDelta} · ${minutes ? mins(minutes) + '長い' : 'ほぼ同じ時間'}`;
}

function render(data, query) {
  const plans = data.options.length ? [...data.options, data.local_only] : [data.local_only];
  result = {query, shift: data.shift, plans};
  showTrip(query, data);
  $('all-candidates').hidden = false;
  $('route-notes').hidden = false;
  $('approximate').hidden = !data.approximate;
  $('alternatives').hidden = plans.length === 1;
  $('baseline').textContent = `一般道だけなら 約 ${mins(data.local_only.minutes)}`;
  $('choices').innerHTML = plans.length === 1 ? '' : plans.map((plan, index) => `
    <button class="choice" type="button" data-choice="${index}">
      <strong>${esc(index === 0 ? '最速' : plan.label)}</strong>
      <span>${minsHtml(plan.minutes)} · ${yenHtml(plan.fare)}</span>
      <small>${index === 0 ? esc(icPair(plan)) : relativeToFastest(plan, plans[0])}</small>
    </button>`).join('');
  showChosen(0);

  const shift = data.shift;
  $('shift').hidden = !shift;
  if (shift) {
    const shiftDate = offsetDeparture(query.depart, shift.offset);
    const when = shiftDate.slice(0, 10) === query.depart.slice(0, 10)
      ? shift.depart : shiftDate.slice(5, 10).replace('-', '/') + ' ' + shift.depart;
    $('shift-summary').textContent = `${when} 出発 · 約 ${mins(shift.minutes)} · 高速代 ${yen(shift.fare)}（最速ルートより ${yen(shift.saving)}安い）`;
  }

  const longest = Math.max(1, ...data.front.map((plan) => plan.minutes));
  $('candidates').innerHTML = data.front.map((plan) => {
    const discounts = plan.runs.map((run) => run.discount).filter(Boolean);
    const label = [icPair(plan), ...discounts, plan.yen_per_min != null && `短縮 1 分あたり ${yen(plan.yen_per_min)}`]
      .filter(Boolean).join(' · ');
    return `<li>
      <div>
        <strong>${minsHtml(plan.minutes)}</strong>
        <span class="time-bar" aria-hidden="true" style="width: ${100 * plan.minutes / longest}%"></span>
        <small>${esc(label)}</small>
      </div>
      <button class="button secondary" data-fare="${plan.fare}" type="button"
        aria-label="${yen(plan.fare)}の予算で探す">${yen(plan.fare)}</button>
    </li>`;
  }).join('');
  $('notes').innerHTML = data.notes.map((note) => `<li>${esc(note)}</li>`).join('');
}

function googleFareStatus(route) {
  if (route.fare === null) return '料金不明';
  return route.within_budget ? '予算内' : '予算超過';
}

function showGoogleChosen(index) {
  const route = result.plans[index];
  const best = index >= 0 && index === result.bestIndex;
  const cheapest = index === result.cheapestIndex;
  const balanced = index === result.balanceIndex;
  const fastest = result.plans[result.bestIndex];
  const title = best ? '予算内で最速の候補' : cheapest ? '安さ重視の候補' :
    balanced ? '速さと安さのバランス（お得）' : route ? googleFareStatus(route) :
    result.plans.length ? '予算内と確認できた候補はありません' : 'ルート候補が見つかりませんでした';
  const google = new URL(route?.nav?.google ?? result.nav.google);
  if (route?.fare === 0) google.searchParams.set('avoid', 'tolls');
  const difference = !best && (cheapest || balanced) && fastest ? relativeToFastest(route, fastest) : '';
  $('chosen').innerHTML = `
    ${route ? `<p class="chosen-tag">${best ? 'おすすめ' : '選択中の候補'}</p>` : ''}
    <h2 id="chosen-title" tabindex="-1">${title}</h2>
    ${route ? `
      <dl class="metrics">
        <div><dt>所要時間</dt><dd class="big">${minsHtml(route.minutes)}</dd>
          <dd class="sub"><span class="num">${esc(route.arrive)}</span> ごろ着</dd></div>
        <div><dt>ETC 推定料金</dt><dd class="big">${route.fare === null ? '不明' : yenHtml(route.fare)}</dd></div>
      </dl>
      <p class="route-line"><strong>${esc(route.description)}</strong> · ${esc(route.distance_km)} km</p>
      ${difference ? `<p class="route-saving">${difference}</p>` : ''}
      ${cheapest && !route.within_budget ? '<p class="chosen-reason">この候補も予算を超えています。</p>' : ''}` : ''}
    <div class="nav-actions">
      <a class="button primary" href="${esc(google.href)}" target="_blank" rel="noopener noreferrer">Google マップで経路を再検索</a>
    </div>
    <p class="muted">Google マップで再検索すると、経路や高速代が変わることがあります。</p>
    ${result.lowCostSearchFailed ? '<p class="muted">有料道路を避ける候補を取得できませんでした。</p>' : ''}
    <p class="muted">経路・推定料金の提供元 <span translate="no">Google Maps</span></p>`;
}

function renderGoogle(data, query) {
  const plans = data.routes;
  const bestIndex = plans.findIndex((route) => route.within_budget);
  const cheapestIndex = data.cheapest_index;
  const balanceIndex = data.balance_index;
  result = {google: true, plans, bestIndex, cheapestIndex, balanceIndex, nav: data.nav, lowCostSearchFailed: data.low_cost_search_failed};
  showTrip(query, data);
  for (const id of ['approximate', 'shift', 'all-candidates', 'route-notes']) $(id).hidden = true;
  $('alternatives').hidden = plans.length === 0 || (plans.length === 1 && bestIndex === 0);
  $('baseline').textContent = 'Google の候補と、乗る・降りる IC を変えた案を、Google の所要時間・ETC 推定料金で比べています（所要時間順）。';
  $('choices').innerHTML = plans.map((route, index) => `
    <button class="choice" type="button" data-choice="${index}">
      <strong>${index === bestIndex ? '予算内で最速' : index === cheapestIndex ? '安さ重視' : index === balanceIndex ? '速さと安さのバランス' : googleFareStatus(route)}</strong>
      <span>${minsHtml(route.minutes)} · ${route.fare === null ? '料金不明' : yenHtml(route.fare)}</span>
      <small>${esc(route.description)} · ${esc(route.distance_km)} km${index === cheapestIndex && !route.within_budget ? ' · 予算超過' : ''}</small>
    </button>`).join('');
  showChosen(bestIndex);
}

async function search(query, {interactive = false} = {}) {
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;
  $('error').hidden = true;
  $('results').hidden = true;
  $('status').classList.remove('visually-hidden');
  $('status').textContent = 'ルートを検索しています…';
  showTrip(query);

  const url = new URL(form.action);
  const {origin, dest, depart, budget} = query;
  url.search = new URLSearchParams({origin, dest, depart, budget, ...(query.now ? {now: '1'} : {})});
  if (googleMode && query.now) url.searchParams.delete('depart');
  try {
    const response = await fetch(url, {signal: request.signal, mode: 'same-origin', cache: 'no-store'});
    const data = await response.json();
    if (request.signal.aborted) return;
    if (!response.ok) throw new Error(data.error || '条件を確認して、もう一度お試しください。');
    const fromGoogle = data.provider === 'google_routes';
    if (fromGoogle) renderGoogle(data, query);
    else render(data, query);
    if (interactive) {
      remember(query);
      $('trip').open = false;
    }
    $('results').hidden = false;
    $('status').classList.add('visually-hidden');
    $('status').textContent = fromGoogle ? '検索が完了しました。' :
      data.approximate ? '近似のルートが見つかりました。' : 'ルートが見つかりました。';
    if (interactive) $('chosen-title').focus();
  } catch (error) {
    if (request.signal.aborted) return;
    $('status').classList.add('visually-hidden');
    $('status').textContent = '';
    $('error').textContent = responseMessage(error);
    $('error').hidden = false;
    $('trip').open = true;
    if (interactive) $('trip').querySelector('summary').focus();
  }
}

function responseMessage(error) {
  if (error instanceof TypeError || error instanceof SyntaxError) {
    return '検索できませんでした。条件を確認して、もう一度お試しください。';
  }
  return error.message;
}

function repeatWith(changes) {
  const query = {...result.query, ...changes};
  if (query.now) query.depart = nowInJapan();  // 「今すぐ」は押した時点の時刻で検索し直す
  endpoints.forEach((id) => fillPoint(id, query[id]));
  $('budget').value = query.budget;
  form.elements['departure-mode'].value = query.now ? 'now' : 'scheduled';
  $('depart').value = query.depart;
  syncDeparture();
  syncPresets();
  search(query, {interactive: true});
}

for (const id of endpoints) {
  $(id + '-select').addEventListener('change', () => {
    syncPoint(id);
    if (!$(id).disabled) $(id).focus();
  });
  $(id).addEventListener('input', () => $(id).setCustomValidity(''));
}
for (const radio of form.elements['departure-mode']) radio.addEventListener('change', syncDeparture);
presets.forEach((button) => button.addEventListener('click', () => {
  $('budget').value = button.dataset.budget;
  syncPresets();
}));
$('budget').addEventListener('input', syncPresets);
$('forget').addEventListener('click', () => {
  try {
    localStorage.removeItem(storageKey);
    $('forget').hidden = true;
    $('trip').querySelector('summary').focus();
    $('status').classList.add('visually-hidden');
    $('status').textContent = '保存した地点と予算を消しました。';
  } catch {
    $('status').classList.remove('visually-hidden');
    $('status').textContent = '保存した地点と予算を消せませんでした。';
  }
});
form.addEventListener('submit', (event) => {
  event.preventDefault();
  for (const id of endpoints) {
    if (!$(id).disabled && !$(id).value.trim()) {
      $(id).setCustomValidity('住所または緯度経度を入力してください。');
      $(id).reportValidity();
      return;
    }
  }
  search(formQuery(), {interactive: true});
});
$('choices').addEventListener('click', (event) => {
  const button = event.target.closest('[data-choice]');
  if (!button) return;
  showChosen(Number(button.dataset.choice));
  $('chosen-title').focus();
});
$('candidates').addEventListener('click', (event) => {
  const button = event.target.closest('[data-fare]');
  if (button) repeatWith({budget: button.dataset.fare});
});
$('apply-shift').addEventListener('click', () => {
  repeatWith({depart: offsetDeparture(result.query.depart, result.shift.offset), now: false});
});

loadPrevious();
syncPresets();
if (googleMode) showTrip(formQuery());
else search(formQuery());
