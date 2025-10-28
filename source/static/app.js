// STAR Dashboard – Personal Use Only
// Licensed under the Personal Use Source License (PUSL)
// Copyright © 2025 Sai Vamsi Karnam
// Attribution Required – No Commercial Use Permitted
// See LICENSE for full terms


// Helpers
const qs = (s, el=document) => el.querySelector(s);
const qsa = (s, el=document) => Array.from(el.querySelectorAll(s));

function openModal(id){ const el = qs(id); if(!el) return; el.classList.remove('hidden'); el.setAttribute('aria-hidden','false'); }
function closeModal(el){ el.classList.add('hidden'); el.setAttribute('aria-hidden','true'); }

// Add Task modal
const addBtn = qs('#addTaskBtn');
const addModal = qs('#addTaskModal');
addBtn && addBtn.addEventListener('click', () => openModal('#addTaskModal'));
qsa('[data-close]', addModal).forEach(btn => btn.addEventListener('click', () => closeModal(addModal)));

// Task detail modal
const detailModal = qs('#taskDetailModal');
qs('body').addEventListener('click', async (e) => {
  const card = e.target.closest('.card.task');
  if(card){
    const id = card.getAttribute('data-task-id');
    const res = await fetch(`/tasks/${id}`);
    const html = await res.text();
    qs('#taskDetailContent').innerHTML = html;
    qsa('[data-close]', detailModal).forEach(btn => btn.addEventListener('click', () => closeModal(detailModal)));
    openModal('#taskDetailModal');
  }
});

// Save meta
window.saveTaskMeta = async function(taskId){
  const form = qs('#taskMetaForm');
  const fd = new FormData(form);
  const res = await fetch(`/tasks/${taskId}/update`, { method: 'POST', body: fd });
  if(res.ok){ closeModal(detailModal); window.location.reload(); }
  else { alert('Failed to save changes'); }
}

// Delete task
window.deleteTask = async function(taskId){
  if(!confirm('Delete this task? This cannot be undone.')) return;
  const res = await fetch(`/tasks/${taskId}/delete`, { method: 'POST' });
  if(res.ok){ closeModal(detailModal); window.location.reload(); }
  else { alert('Failed to delete task'); }
}

// Intercept attachment form submits to avoid full-page navigation
document.body.addEventListener('submit', async (e) => {
  const form = e.target.closest('.attach-form');
  if (!form) return;

  e.preventDefault();
  const fd = new FormData(form);

  // mark as fetch so the server can return 204
  const res = await fetch(form.action, {
    method: 'POST',
    body: fd,
    headers: { 'X-Requested-With': 'fetch' }
  });

  if (res.ok) {
    // Re-load the modal content to show new attachments
    const m = form.action.match(/tasks\/(\d+)\/attachments/);
    const taskId = m ? m[1] : null;
    if (taskId) {
      const html = await (await fetch(`/tasks/${taskId}`)).text();
      document.querySelector('#taskDetailContent').innerHTML = html;
      // re-bind close buttons in the refreshed modal
      document.querySelectorAll('#taskDetailModal [data-close]')
        .forEach(btn => btn.addEventListener('click', () => {
          const modal = document.querySelector('#taskDetailModal');
          modal.classList.add('hidden');
          modal.setAttribute('aria-hidden', 'true');
        }));
    } else {
      // fallback: full page refresh
      window.location.reload();
    }
  } else {
    alert('Upload failed');
  }
});

// Drag & Drop
let dragged = null;
function wireDrag(){
  qsa('.card.task').forEach(card => {
    card.addEventListener('dragstart', (e) => {
      dragged = card;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', card.getAttribute('data-task-id'));
      setTimeout(() => card.classList.add('dragging'), 0);
    });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); dragged = null; });
  });
}
function wireDropzones(){
  qsa('.dropzone').forEach(zone => {
    zone.addEventListener('dragover', (e) => {
      e.preventDefault(); zone.classList.add('over');
      const after = getDragAfterElement(zone, e.clientY);
      if(after == null){ zone.appendChild(dragged); }
      else { zone.insertBefore(dragged, after); }
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', async (e) => {
      e.preventDefault(); zone.classList.remove('over');
      const newStatus = zone.getAttribute('data-status');
      const id = dragged.getAttribute('data-task-id');
      const position = 1 + qsa('.card.task', zone).indexOf(dragged);
      try{
        const res = await fetch('/update_status', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: parseInt(id), new_status: newStatus, new_position: position })
        });
        const data = await res.json();
        if(!res.ok || !data.ok){ alert('Failed to update status'); }
      }catch(err){ console.error(err); alert('Network error'); }
    });
  });
}
function getDragAfterElement(container, y){
  const els = qsa('.card.task:not(.dragging)', container);
  let closest = { offset: Number.NEGATIVE_INFINITY, element: null };
  els.forEach(el => { const box = el.getBoundingClientRect(); const offset = y - box.top - box.height/2; if(offset < 0 && offset > closest.offset){ closest = { offset, element: el }; } });
  return closest.element;
}
wireDrag(); wireDropzones();

// Info modal
const infoBtn = qs('#infoBtn');
const infoModal = qs('#infoModal');
infoBtn && infoBtn.addEventListener('click', () => openModal('#infoModal'));
qsa('[data-close]', infoModal).forEach(btn => btn.addEventListener('click', () => closeModal(infoModal)));