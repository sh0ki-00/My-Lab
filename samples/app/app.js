// samples/app/app.js — 注文一覧の絞り込みと、済の群の開閉と、選んだ件数に合わせた主ボタンの置き場。段階 3 の見本なので、表示と取得を分けず 1 ファイルに置く。
// 開閉の印は open の 1 つだけ。状態で「済」に絞ったときは open を立ててから描き直す（監修 8 回目の指摘 1）。
// 入力（文字）と状態の 2 条件で行を隠し、群ごとの件数を直す。「済」に絞ると、出荷指示の直後の群も当たる。絞り込んだときだけ、当たった件数を検索欄の右に出す。
// 済の群の見出しは開閉のボタンを兼ねる。件数は絞り込みが無いときは全体（data-total）、あるときは当たった行の数。
(() => {
  const q = document.getElementById('q');
  const st = document.getElementById('st');
  const count = document.getElementById('count');
  const empty = document.getElementById('empty');
  const rows = Array.from(document.querySelectorAll('#orders tbody tr[data-status]'));
  const groups = Array.from(document.querySelectorAll('#orders tbody[data-group]'));
  const toggle = document.querySelector('.done-head button');
  const doneHead = document.querySelector('tbody[data-group="done-head"]');
  const doneRows = document.getElementById('done-rows');
  let open = false;

  const apply = () => {
    const text = q.value.trim().toLowerCase();
    const status = st.value;
    const filtered = Boolean(text || status);
    const perGroup = {};
    let shown = 0;
    for (const row of rows) {
      const hit = (!text || row.textContent.toLowerCase().includes(text)) && (!status || row.dataset.status === status || (status === 'done' && row.dataset.status === 'shipped'));
      row.hidden = !hit;
      if (hit) {
        perGroup[row.dataset.status] = (perGroup[row.dataset.status] || 0) + 1;
        if (row.dataset.status !== 'done') shown += 1;
      }
    }
    for (const g of groups) {
      if (g === doneHead || g === doneRows) continue;
      const n = perGroup[g.dataset.group] || 0;
      g.hidden = n === 0;
      g.querySelector('.group-count').textContent = `${n}件`;
    }
    const done = perGroup.done || 0;
    const doneCount = filtered ? done : Number(doneHead.dataset.total);
    doneHead.hidden = filtered && done === 0;
    doneHead.querySelector('.group-count').textContent = `${doneCount}件`;
    const showDone = open && done > 0;
    doneRows.hidden = !showDone;
    toggle.setAttribute('aria-expanded', String(showDone));
    toggle.querySelector('.open-label').textContent = showDone ? '閉じる' : '開く';
    count.textContent = filtered ? `${shown + done}件` : '';
    empty.hidden = shown + done !== 0;
  };

  toggle.addEventListener('click', () => {
    open = !open;
    apply();
  });
  q.addEventListener('input', apply);
  st.addEventListener('change', () => {
    if (st.value === 'done') open = true;
    apply();
  });
  document.querySelector('form').addEventListener('submit', (event) => event.preventDefault());

  // 主ボタン（墨の地）は画面に 1 つ。行を選んでいれば一括操作の帯の「N件を出荷指示」、選んでいなければ伝票の「この1件を出荷指示」
  const bulk = document.querySelector('.bulkbar');
  const picked = bulk.querySelector('.picked');
  const shipBulk = bulk.querySelector('.ship-bulk');
  const shipOne = document.querySelector('.ship-one');
  const all = document.querySelector('#orders thead .pick input');
  const boxOf = (row) => row.querySelector('.pick input');
  const sync = () => {
    let n = 0;
    for (const row of rows) {
      const on = boxOf(row).checked;
      row.classList.toggle('is-selected', on);
      if (on) n += 1;
    }
    bulk.hidden = n === 0;
    picked.textContent = `${n}件を選択`;
    shipBulk.textContent = `${n}件を出荷指示`;
    shipBulk.classList.toggle('primary', n > 0);
    shipOne.classList.toggle('primary', n === 0);
  };
  for (const row of rows) boxOf(row).addEventListener('change', sync);
  all.addEventListener('change', () => {
    for (const row of rows) if (!row.hidden && !row.closest('[hidden]')) boxOf(row).checked = all.checked;
    sync();
  });
  apply();
  sync();
})();
