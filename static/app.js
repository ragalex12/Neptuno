// Vanilla JS functions replacing previous jQuery based logic

function q(sel) { return document.querySelector(sel); }
function qa(sel){
  if (typeof sel === 'string') return Array.from(document.querySelectorAll(sel));
  return Array.from(sel);
}

function toggleActive(e){ e.currentTarget.classList.toggle('active'); }

function initSelectable(scope){
  qa(scope + ' .list-group-item').forEach(li=>{
    li.addEventListener('click', toggleActive);
    li.setAttribute('draggable', 'true');
  });
}

function enableDnD(listSel){
  const list = q(listSel);
  if(!list) return;
  list.addEventListener('dragstart', e=>{
    if(e.target.matches('li')) e.target.classList.add('dragging');
  });
  list.addEventListener('dragend', e=>{
    if(e.target.matches('li')) e.target.classList.remove('dragging');
  });
  list.addEventListener('dragover', e=>{
    e.preventDefault();
    const dragging = q('.dragging');
    if(!dragging) return;
    const after = Array.from(list.querySelectorAll('li:not(.dragging)'))
      .find(li => e.clientY <= li.getBoundingClientRect().top + li.offsetHeight/2);
    if(after) list.insertBefore(dragging, after); else list.appendChild(dragging);
  });
  list.addEventListener('drop', e=>{ e.preventDefault(); });
}

function filterInput(inputSel, listSel){
  const input = q(inputSel);
  const list  = q(listSel);
  if(!input || !list) return;
  input.addEventListener('input', ()=>{
    const term = input.value.toLowerCase();
    qa(list.children).forEach(li=>{
      li.style.display = li.textContent.toLowerCase().includes(term) ? '' : 'none';
    });
  });
}

function moveItems(fromSel, toSel, all){
  const from = q(fromSel), to = q(toSel);
  if(!from || !to) return;
  const items = all ? qa(from.children) : qa(from.querySelectorAll('.active'));
  items.forEach(li=>{ li.classList.remove('active'); to.appendChild(li); });
}

function moveUp(listSel){
  const list = q(listSel);
  qa(list.querySelectorAll('.active')).forEach(li=>{
    const prev = li.previousElementSibling;
    if(prev) list.insertBefore(li, prev);
  });
}

function moveDown(listSel){
  const list = q(listSel);
  qa(list.querySelectorAll('.active')).reverse().forEach(li=>{
    const next = li.nextElementSibling;
    if(next) list.insertBefore(next, li);
  });
}

function serializeList(listSel, param){
  const params = new URLSearchParams();
  qa(listSel + ' li').forEach(li=> params.append(param, li.dataset.rpro));
  return params;
}

function post(url, params){
  return fetch(url, {method:'POST', body: params});
}

document.addEventListener('DOMContentLoaded', ()=>{
  // ----- Inventory Mapping -----
  if(q('#saveMapping')){
    initSelectable('#availableFields');
    initSelectable('#selectedFields');
    enableDnD('#availableFields');
    enableDnD('#selectedFields');
    filterInput('#search-available', '#availableFields');
    filterInput('#search-selected', '#selectedFields');

    q('#btn-add')   .addEventListener('click', ()=>moveItems('#availableFields','#selectedFields'));
    q('#btn-addAll').addEventListener('click', ()=>moveItems('#availableFields','#selectedFields', true));
    q('#btn-remove').addEventListener('click', ()=>moveItems('#selectedFields','#availableFields'));
    q('#btn-removeAll').addEventListener('click', ()=>moveItems('#selectedFields','#availableFields', true));
    q('#btn-up')    .addEventListener('click', ()=>moveUp('#selectedFields'));
    q('#btn-down')  .addEventListener('click', ()=>moveDown('#selectedFields'));

    q('#saveMapping').addEventListener('click', ()=>{
      const params = serializeList('#selectedFields', 'campos[]');
      post('/guardar_config', params).then(()=>alert('Mapping saved'))
        .catch(()=>alert('Error al guardar mapping'));
    });
  }

  // ----- Transfer Orders Mapping -----
  if(q('#saveMappingTO')){
    ['#availableTOH','#selectedTOH','#availableTOI','#selectedTOI'].forEach(s=>initSelectable(s));
    ['#availableTOH','#selectedTOH','#availableTOI','#selectedTOI'].forEach(enableDnD);
    filterInput('#search-available-to-h','#availableTOH');
    filterInput('#search-selected-to-h','#selectedTOH');
    filterInput('#search-available-to-i','#availableTOI');
    filterInput('#search-selected-to-i','#selectedTOI');

    q('#btn-add-to-h').addEventListener('click', ()=>moveItems('#availableTOH','#selectedTOH'));
    q('#btn-remove-to-h').addEventListener('click', ()=>moveItems('#selectedTOH','#availableTOH'));
    q('#btn-add-to-i').addEventListener('click', ()=>moveItems('#availableTOI','#selectedTOI'));
    q('#btn-remove-to-i').addEventListener('click', ()=>moveItems('#selectedTOI','#availableTOI'));

    q('#saveMappingTO').addEventListener('click', ()=>{
      const params = new URLSearchParams();
      qa('#selectedTOH li').forEach(li=>params.append('header[]', li.dataset.rpro));
      qa('#selectedTOI li').forEach(li=>params.append('detail[]', li.dataset.rpro));
      post('/guardar_config_to', params)
        .then(r=>r.json())
        .then(res=>{
          if(res.ok) alert('Mapping TO guardado con éxito');
          else alert('Error al guardar Mapping TO:\n' + (res.error||''));
        })
        .catch(()=>alert('Error al guardar Mapping TO'));
    });

    q('#generateFormTO').addEventListener('submit', e=>{
      e.preventDefault();
      const form = new FormData(e.target);
      fetch('/generar_to', {method:'POST', body:form})
        .then(r=>r.json())
        .then(res=>{
          if(res.status==='success') alert('XML TO generado en:\n'+res.path);
          else alert('Error al generar XML TO:\n'+(res.error||''));
        })
        .catch(()=>alert('Error al generar XML TO'))
        .finally(()=>e.target.reset());
    });
  }

  // ----- Browse output path -----
  if(q('#browseBtn')){
    q('#browseBtn').addEventListener('click', ()=>{
      fetch('/select_folder', {method:'POST'})
        .then(r=>r.json())
        .then(res=>{
          if(res.ruta) q('#outputPath').value = res.ruta;
          else alert(res.error||'No se seleccion\u00f3 carpeta');
        })
        .catch(()=>alert('Error al seleccionar carpeta'));
    });
  }

  // ----- Save CSV Config -----
  if(q('#saveCsvConfig')){
    q('#saveCsvConfig').addEventListener('click', ()=>{
      const delim = q('#csv-delimiter').value;
      const ruta  = q('#outputPath').value;
      fetch('/save_csv_config', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({delimiter:delim, ruta:ruta})
      })
      .then(r=>{if(!r.ok) return r.json().then(x=>Promise.reject(x));})
      .then(()=>alert('Configuración guardada correctamente'))
      .catch(err=>alert(err.error||'Error al guardar configuración'));
    });
  }

  // ----- Generate Inventory XML -----
  if(q('#generateForm')){
    q('#generateForm').addEventListener('submit', e=>{
      e.preventDefault();
      const form = new FormData(e.target);
      fetch('/generar', {method:'POST', body:form})
        .then(r=>r.json())
        .then(res=>{ alert('XML generado en:\n'+res.path); })
        .catch(err=>alert(err.error||'Error desconocido'))
        .finally(()=>e.target.reset());
    });
  }

  // ----- DB Connection -----
  if(q('#dbConfigForm')){
    q('#dbConfigForm').addEventListener('submit', e=>{
      e.preventDefault();
      const params = new URLSearchParams(new FormData(e.target));
      post('/save_connection', params)
        .then(r=>r.json())
        .then(res=>{
          if(res.ok){ alert('Datos Guardados'); location.reload(); }
          else alert('Error: '+res.error);
        })
        .catch(()=>alert('Error al guardar conexión'));
    });

    q('#testConnection').addEventListener('click', ()=>{
      const params = new URLSearchParams(new FormData(q('#dbConfigForm')));
      post('/test_connection', params)
        .then(r=>r.json())
        .then(res=>alert(res.message))
        .catch(()=>alert('Error de conexión'));
    });
  }

  // ----- SID Config -----
  if(q('#sidConfigForm')){
    q('#sidConfigForm').addEventListener('submit', e=>{
      e.preventDefault();
      const data = {
        item_sid_mode: q('#sidConfigForm [name="item_sid_mode"]').value,
        style_sid_mode: q('#sidConfigForm [name="style_sid_mode"]').value
      };
      fetch('/sid-config', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(data)
      })
      .then(r=>{if(!r.ok) return r.json().then(x=>Promise.reject(x));})
      .then(()=>alert('SID Configuración guardada'))
      .catch(err=>alert(err.error||'Error al guardar SID config'));
    });
  }
});
