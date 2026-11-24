import {
  App,
  applyDocumentTheme,
  applyHostStyleVariables,
} from '@modelcontextprotocol/ext-apps';

const app = new App({ name: 'Movie Recap Studio', version: '1.0.0' }, {});

let state = {
  projects: [],
  active_project: null,
  voices: {},
  nvenc_available: false,
  hostCaps: {},
};

const elProjectSelect = document.getElementById('project-select');
const elGpuBadge = document.getElementById('gpu-badge');
const elCacheBadge = document.getElementById('cache-badge');
const elNotice = document.getElementById('notice-banner');
const elMainPlayer = document.getElementById('main-player');
const elAudioPlayer = document.getElementById('audio-player');
const elNowPlaying = document.getElementById('now-playing-label');
const elBtnPlayFull = document.getElementById('btn-play-full');
const elChapters = document.getElementById('chapters-container');
const elCharList = document.getElementById('char-list');
const elStoryboards = document.getElementById('storyboard-list');
const elDriveLinks = document.getElementById('drive-links');
const elWipeDialog = document.getElementById('wipe-dialog');

function showNotice(msg) {
  if (!msg) {
    elNotice.classList.remove('visible');
    return;
  }
  elNotice.textContent = msg;
  elNotice.classList.add('visible');
}

function fmtSec(sec) {
  const s = Math.max(0, Number(sec || 0));
  const m = Math.floor(s / 60);
  const r = (s % 60).toFixed(1).padStart(4, '0');
  return `${String(m).padStart(2, '0')}:${r}`;
}

function setupTabs() {
  const tablist = document.getElementById('studio-tablist');
  const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
  const panels = tabs.map((t) => document.getElementById(t.id.replace('tab-', 'panel-')));

  function selectTab(selectedTab) {
    tabs.forEach((tab, idx) => {
      const isSel = tab === selectedTab;
      tab.ariaSelected = String(isSel);
      tab.toggleAttribute('focusgroupstart', isSel);
      const panel = panels[idx];
      if (isSel) {
        panel.hidden = false;
      } else {
        panel.setAttribute('hidden', 'until-found');
      }
    });
    selectedTab.scrollIntoView({ block: 'nearest', inline: 'nearest', container: 'nearest' });
  }

  tabs.forEach((tab, idx) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('focus', () => selectTab(tab));
    tab.addEventListener('keydown', (e) => {
      // Fallback arrow key roving when native focusgroup is absent
      if (!Object.hasOwn(HTMLElement.prototype, 'focusGroup')) {
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          e.preventDefault();
          const dir = e.key === 'ArrowRight' ? 1 : -1;
          const next = tabs[(idx + dir + tabs.length) % tabs.length];
          next.focus();
        }
      }
    });
    panels[idx].addEventListener('beforematch', () => selectTab(tab));
  });

  if (!CSS.supports('animation-timeline', 'scroll()')) {
    const first = tablist.firstElementChild;
    const last = tablist.lastElementChild;
    if (first && last) {
      const observer = new IntersectionObserver(
        (entries) => {
          for (const { target, intersectionRatio } of entries) {
            tablist.classList.toggle(
              target === first ? 'more-start' : 'more-end',
              intersectionRatio < 1
            );
          }
        },
        { root: tablist, threshold: 1, rootMargin: '1px' }
      );
      observer.observe(first);
      observer.observe(last);
    }
  }
}

function playVideo(url, label) {
  if (!url) {
    showNotice('Chưa có file video xem trước cho mục này. Hãy bấm Render xem trước!');
    return;
  }
  elAudioPlayer.pause();
  elAudioPlayer.style.display = 'none';
  elMainPlayer.src = url;
  elMainPlayer.play().catch(() => {});
  elNowPlaying.textContent = `Đang phát: ${label}`;
}

function playAudio(url, label) {
  if (!url) {
    showNotice('Chưa có file thoại TTS cho câu này. Hãy bấm Lưu & TTS!');
    return;
  }
  elMainPlayer.pause();
  elAudioPlayer.style.display = 'block';
  elAudioPlayer.src = url;
  elAudioPlayer.play().catch(() => {});
  elNowPlaying.textContent = `Đang nghe thoại: ${label}`;
}

async function callTool(name, args = {}, loadingMsg = 'Đang xử lý...') {
  try {
    showNotice(loadingMsg);
    const res = await app.callServerTool({ name, arguments: args });
    if (res && res.structuredContent) {
      applyState(res.structuredContent);
    }
    return res;
  } catch (err) {
    showNotice(`Lỗi: ${err?.message || String(err)}`);
    return null;
  }
}

async function sendPromptToChat(text, contextText = '') {
  const caps = app.getHostCapabilities() || {};
  if (caps.updateModelContext && contextText) {
    await app.updateModelContext({
      content: [{ type: 'text', text: contextText }],
    });
  }
  if (caps.message) {
    await app.sendMessage({
      role: 'user',
      content: [{ type: 'text', text }],
    });
    showNotice('Đã gửi yêu cầu sang khung Chat bên trái!');
  } else {
    showNotice('Mở khung này ở chế độ Side Pane cạnh cuộc trò chuyện để gửi lệnh trực tiếp sang khung Chat.');
  }
}

function renderCharacters(proj) {
  elCharList.innerHTML = '';
  const chars = proj?.character_bible || [];
  if (!chars.length) {
    const hint = document.createElement('div');
    hint.className = 'empty-box';
    hint.textContent = 'Chưa có nhân vật nào. Bấm "+ Thêm nhân vật" để cố định biệt danh xuyên suốt 10 chương.';
    elCharList.appendChild(hint);
    return;
  }
  chars.forEach((c, idx) => {
    const row = document.createElement('div');
    row.className = 'char-grid';
    row.innerHTML = `
      <input type="text" data-field="original_name" placeholder="Tên gốc (VD: Sato)" value="${(c.original_name || '').replace(/"/g, '&quot;')}">
      <input type="text" data-field="alias" placeholder="Biệt danh (VD: Anh main sát thủ)" value="${(c.alias || '').replace(/"/g, '&quot;')}">
      <input type="text" data-field="role" placeholder="Vai trò / Ghi chú" value="${(c.role || '').replace(/"/g, '&quot;')}">
      <button type="button" class="danger" title="Xóa">✕</button>
    `;
    row.querySelector('button').addEventListener('click', () => {
      proj.character_bible.splice(idx, 1);
      renderCharacters(proj);
    });
    elCharList.appendChild(row);
  });
}

function renderStoryboards(proj) {
  elStoryboards.innerHTML = '';
  const sheets = proj?.source?.storyboard_urls || [];
  if (!sheets.length) {
    elStoryboards.innerHTML = '<div class="empty-box" style="grid-column:1/-1">Chưa có bảng ảnh Storyboard (hoặc đã tự dọn sạch sau khi lên Drive).</div>';
    return;
  }
  sheets.forEach((s) => {
    const card = document.createElement('div');
    card.className = 'storyboard-card';
    card.innerHTML = `
      <img src="${s.url}" alt="${s.name}" loading="lazy">
      <div>${s.name}</div>
    `;
    elStoryboards.appendChild(card);
  });
}

function renderChapters(proj) {
  elChapters.innerHTML = '';
  if (!proj) {
    elChapters.innerHTML = `
      <div class="empty-box">
        <strong>Chưa có dự án nào trong D:\\CLIP\\temp_cache</strong>
        <p>Gõ vào khung Chat bên trái đường dẫn phim hoặc link Google Drive (ví dụ: <em>"Tạo review 45 phút cho phim..."</em>) hoặc bấm nút <strong>✨ Giao AI làm phim mới ở Chat</strong> ở trên!</p>
      </div>
    `;
    return;
  }

  const chapters = proj.chapters || [];
  if (!chapters.length) {
    elChapters.innerHTML = `
      <div class="empty-box">
        Dự án <strong>${proj.title}</strong> đã sẵn sàng, chưa có Chương nào. Hãy nhắn bên khung Chat để AI chia chương &amp; viết kịch bản!
      </div>
    `;
    return;
  }

  chapters.forEach((ch) => {
    const card = document.createElement('div');
    card.className = 'chapter-card';
    const chDur = (ch.blocks || []).reduce((acc, b) => acc + Number(b.audio_duration_sec || 0), 0);

    const header = document.createElement('div');
    header.className = 'chapter-header';
    header.innerHTML = `
      <div>
        <strong>${ch.title || ch.chapter_id}</strong>
        <span class="badge">${(ch.blocks || []).length} cảnh • ${fmtSec(chDur)}</span>
      </div>
      <div class="toolbar">
        <button type="button" class="btn-ch-render">🎬 Render Chương</button>
        <button type="button" class="btn-ch-play" ${ch.chapter_video_url ? '' : 'disabled'}>▶ Xem Chương</button>
        <button type="button" class="btn-ch-ai">💬 Sửa Chương bằng AI</button>
      </div>
    `;

    header.querySelector('.btn-ch-render').addEventListener('click', () => {
      callTool('recap_render_preview', { project_id: proj.project_id, chapter_id: ch.chapter_id }, `Đang render ${ch.title} bằng GPU...`);
    });
    header.querySelector('.btn-ch-play').addEventListener('click', () => {
      playVideo(ch.chapter_video_url, ch.title || ch.chapter_id);
    });
    header.querySelector('.btn-ch-ai').addEventListener('click', () => {
      sendPromptToChat(
        `Hãy chỉnh sửa lại chương ${ch.chapter_id} (${ch.title}) của dự án ${proj.project_id} cho kịch tính và cuốn hút hơn.`,
        JSON.stringify({ project_id: proj.project_id, chapter_id: ch.chapter_id, blocks: ch.blocks }, null, 2)
      );
    });
    card.appendChild(header);

    (ch.blocks || []).forEach((blk) => {
      const bdiv = document.createElement('div');
      bdiv.className = 'block-item';
      const firstClip = (blk.clips && blk.clips[0]) || { start_sec: 0, end_sec: 3.5 };
      const clipSummary = (blk.clips || [])
        .map((c) => `${fmtSec(c.start_sec)}→${fmtSec(c.end_sec)}${c.flip_h ? ' [Flip]' : ''}`)
        .join(', ');

      bdiv.innerHTML = `
        <div class="block-meta">
          <span><strong>${blk.block_id}</strong> • Thoại: ${Number(blk.audio_duration_sec || 0).toFixed(1)}s</span>
          <span>Cảnh gốc: ${clipSummary || 'Chưa gán'}</span>
        </div>
        <textarea aria-label="Lời bình ${blk.block_id}">${blk.narration || ''}</textarea>
        <div class="block-actions">
          <input type="number" step="0.5" min="0" style="width:86px" title="Giây bắt đầu cảnh gốc" value="${Number(firstClip.start_sec || 0)}">
          <button type="button" class="btn-blk-save primary">💾 Lưu &amp; Đọc lại (3s)</button>
          <button type="button" class="btn-blk-audio" ${blk.audio_url ? '' : 'disabled'}>🔊 Nghe</button>
          <button type="button" class="btn-blk-video" ${blk.preview_clip_url ? '' : 'disabled'}>🎬 Xem clip</button>
          <button type="button" class="btn-blk-chat">✨ Prompt sửa cảnh này</button>
        </div>
      `;

      const ta = bdiv.querySelector('textarea');
      const inpStart = bdiv.querySelector('input[type="number"]');

      bdiv.querySelector('.btn-blk-save').addEventListener('click', () => {
        callTool(
          'recap_edit_block',
          {
            project_id: proj.project_id,
            block_id: blk.block_id,
            narration: ta.value,
            start_sec: Number(inpStart.value),
            end_sec: Number(inpStart.value) + Math.max(3.2, Number(blk.audio_duration_sec || 3.5)),
            render_preview: true,
          },
          `Đang cập nhật nhanh cảnh ${blk.block_id}...`
        );
      });
      bdiv.querySelector('.btn-blk-audio').addEventListener('click', () => {
        playAudio(blk.audio_url, blk.block_id);
      });
      bdiv.querySelector('.btn-blk-video').addEventListener('click', () => {
        playVideo(blk.preview_clip_url, `Cảnh ${blk.block_id}`);
      });
      bdiv.querySelector('.btn-blk-chat').addEventListener('click', async () => {
        const caps = app.getHostCapabilities() || {};
        const ctxStr = `Dự án: ${proj.project_id} | Cảnh: ${blk.block_id}\nLời bình hiện tại: "${ta.value}"\nMốc cảnh gốc: ${clipSummary}`;
        if (caps.updateModelContext) {
          await app.updateModelContext({ content: [{ type: 'text', text: ctxStr }] });
          showNotice(`Đã đính kèm cảnh ${blk.block_id} vào ô Chat bên trái! Bạn chỉ cần gõ yêu cầu sửa.`);
        } else {
          sendPromptToChat(`Sửa cảnh ${blk.block_id} trong dự án ${proj.project_id}: `, ctxStr);
        }
      });

      card.appendChild(bdiv);
    });

    elChapters.appendChild(card);
  });
}

function applyState(payload) {
  if (!payload) return;
  state = { ...state, ...payload };

  elGpuBadge.textContent = state.nvenc_available ? '⚡ GPU: NVIDIA NVENC' : 'CPU: libx264';
  elGpuBadge.className = `badge ${state.nvenc_available ? 'ok' : 'warn'}`;

  const proj = state.active_project;
  const cacheMb = proj ? Number(proj.cache_size_mb || 0) : 0;
  const cleaned = proj?.exports?.local_cache_cleaned;
  elCacheBadge.textContent = cleaned
    ? `🧹 Đệm D:\\CLIP: ${cacheMb} MB (Đã dọn sạch)`
    : `💾 Đệm D:\\CLIP: ${cacheMb} MB`;
  elCacheBadge.className = `badge ${cacheMb <= 1 ? 'ok' : ''}`;

  if (payload.notice) {
    showNotice(payload.notice);
  }

  // Projects dropdown
  elProjectSelect.innerHTML = '';
  if (!(state.projects || []).length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '(Chưa có dự án)';
    elProjectSelect.appendChild(opt);
  } else {
    state.projects.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.project_id;
      opt.textContent = `${p.title} (${Math.round((p.estimated_duration_sec || 0) / 60)}p)`;
      if (proj && p.project_id === proj.project_id) opt.selected = true;
      elProjectSelect.appendChild(opt);
    });
  }

  // Voices dropdown
  const elVoice = document.getElementById('cfg-voice');
  elVoice.innerHTML = '';
  Object.entries(state.voices || {}).forEach(([k, label]) => {
    const opt = document.createElement('option');
    opt.value = k;
    opt.textContent = label;
    if (proj?.voice_settings?.voice === k) opt.selected = true;
    elVoice.appendChild(opt);
  });

  if (proj) {
    document.getElementById('cfg-rate').value = proj.voice_settings?.rate || '+14%';
    document.getElementById('cfg-aspect').value = proj.export_settings?.aspect_ratio || '16:9';
    document.getElementById('cfg-drive-folder').value = proj.export_settings?.drive_folder_name || 'Movie Recap Studio';
    document.getElementById('cfg-burn-sub').checked = Boolean(proj.export_settings?.burn_subtitles);
    document.getElementById('cfg-nvenc').checked = Boolean(proj.export_settings?.use_nvenc ?? true);
    document.getElementById('cfg-autoclean').checked = Boolean(proj.export_settings?.auto_clean_local ?? true);

    const fullUrl = proj.exports?.mp4_stream_url || '';
    elBtnPlayFull.disabled = !fullUrl;
    elBtnPlayFull.onclick = () => playVideo(fullUrl, `${proj.title} (Full MP4)`);

    const links = [];
    if (proj.exports?.drive_mp4_url) {
      links.push(`<div>✅ <strong>Link Video MP4 trên Google Drive:</strong> <a href="${proj.exports.drive_mp4_url}" target="_blank" rel="noopener">${proj.exports.drive_mp4_url}</a></div>`);
    }
    if (proj.exports?.drive_srt_url) {
      links.push(`<div>📝 <strong>Link Phụ đề .SRT trên Drive:</strong> <a href="${proj.exports.drive_srt_url}" target="_blank" rel="noopener">${proj.exports.drive_srt_url}</a></div>`);
    }
    if (proj.exports?.kdenlive_path) {
      links.push(`<div>🛠️ <strong>Kdenlive XML:</strong> <code>${proj.exports.kdenlive_path}</code></div>`);
    }
    elDriveLinks.innerHTML = links.join('');
  } else {
    elBtnPlayFull.disabled = true;
    elDriveLinks.innerHTML = '';
  }

  renderChapters(proj);
  renderCharacters(proj);
  renderStoryboards(proj);
}

// Wire static controls
elProjectSelect.addEventListener('change', () => {
  if (elProjectSelect.value) {
    callTool('app_get_state', { project_id: elProjectSelect.value }, 'Đang chuyển dự án...');
  }
});

document.getElementById('btn-refresh').addEventListener('click', () => {
  const pid = state.active_project?.project_id || '';
  callTool('app_get_state', { project_id: pid }, 'Đang làm mới...');
});

document.getElementById('btn-prompt-new').addEventListener('click', () => {
  sendPromptToChat(
    'Mình muốn tạo một dự án video Review Phim mới trong Movie Recap Studio (dài khoảng 45-60 phút, lưu tạm ở D:\\CLIP, xong đẩy lên Google Drive). Hãy hỏi mình nguồn phim để bắt đầu!'
  );
});

document.getElementById('btn-add-char').addEventListener('click', () => {
  if (!state.active_project) return;
  state.active_project.character_bible = state.active_project.character_bible || [];
  state.active_project.character_bible.push({ original_name: '', alias: '', role: '' });
  renderCharacters(state.active_project);
});

document.getElementById('btn-save-char').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  const rows = Array.from(elCharList.querySelectorAll('.char-grid'));
  const characters = rows
    .map((r) => ({
      original_name: r.querySelector('[data-field="original_name"]').value.trim(),
      alias: r.querySelector('[data-field="alias"]').value.trim(),
      role: r.querySelector('[data-field="role"]').value.trim(),
    }))
    .filter((c) => c.original_name || c.alias);
  callTool('recap_set_character_bible', { project_id: proj.project_id, characters }, 'Đang lưu Từ điển Nhân vật...');
});

document.getElementById('btn-gen-storyboard').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  callTool('recap_generate_storyboards', { project_id: proj.project_id, interval_sec: 15 }, 'Đang trích xuất bảng ảnh Storyboard 5x5...');
});

document.getElementById('btn-save-settings').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  callTool(
    'app_save_settings',
    {
      project_id: proj.project_id,
      voice: document.getElementById('cfg-voice').value,
      rate: document.getElementById('cfg-rate').value.trim() || '+14%',
      aspect_ratio: document.getElementById('cfg-aspect').value,
      burn_subtitles: document.getElementById('cfg-burn-sub').checked,
      use_nvenc: document.getElementById('cfg-nvenc').checked,
      auto_clean_local: document.getElementById('cfg-autoclean').checked,
      drive_folder_name: document.getElementById('cfg-drive-folder').value.trim() || 'Movie Recap Studio',
    },
    'Đang lưu cấu hình...'
  );
});

document.getElementById('btn-tts-all').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  callTool('recap_synthesize_tts', { project_id: proj.project_id, force: false }, 'Đang tạo toàn bộ giọng đọc Edge-TTS & phụ đề .SRT...');
});

document.getElementById('btn-export-kdenlive').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  callTool('recap_export_kdenlive', { project_id: proj.project_id, open_gui: true }, 'Đang xuất file .kdenlive XML...');
});

document.getElementById('btn-render-full').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  const burn = document.getElementById('cfg-burn-sub').checked;
  callTool('recap_render_full_movie', { project_id: proj.project_id, burn_subtitles: burn }, 'Đang render bản Full .MP4 bằng NVIDIA NVENC GPU...');
});

document.getElementById('btn-drive-upload-clean').addEventListener('click', () => {
  const proj = state.active_project;
  if (!proj) return;
  const folder = document.getElementById('cfg-drive-folder').value.trim() || 'Movie Recap Studio';
  const autoClean = document.getElementById('cfg-autoclean').checked;
  sendPromptToChat(
    `Hãy xuất bản hoàn chỉnh dự án "${proj.project_id}": chạy recap_render_full_movie (nếu chưa có bản MP4 mới nhất), sau đó dùng kỹ năng gdrive đẩy file .mp4, .srt và .kdenlive lên thư mục "${folder}" trên Google Drive tài khoản của tôi, lưu lại link qua recap_record_drive_upload(clean_local_now=${autoClean}) và báo lại link Google Drive cho tôi!`
  );
});

document.getElementById('btn-open-wipe-dialog').addEventListener('click', () => {
  if (!state.active_project) return;
  elWipeDialog.showModal();
});

elWipeDialog.addEventListener('close', () => {
  const choice = elWipeDialog.returnValue;
  elWipeDialog.returnValue = '';
  if (choice === 'confirm' && state.active_project) {
    callTool('recap_clean_local_cache', { project_id: state.active_project.project_id, delete_entire_project: false }, 'Đang dọn sạch bộ đệm video trên D:\\CLIP...');
  }
});

// Register MCP App handlers BEFORE app.connect()
app.ontoolinput = () => {
  showNotice('Đang tải dữ liệu Movie Recap Studio...');
};

app.ontoolresult = (result) => {
  if (result && result.structuredContent) {
    applyState(result.structuredContent);
  }
};

app.onhostcontextchanged = (ctx) => {
  if (ctx.theme) applyDocumentTheme(ctx.theme);
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
};

setupTabs();

(async () => {
  try {
    await app.connect();
    const ctx = app.getHostContext();
    if (ctx?.theme) applyDocumentTheme(ctx.theme);
    if (ctx?.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
    // Eagerly fetch latest state in case entrypoint launched with empty result
    await callTool('app_get_state', {}, '');
  } catch (err) {
    showNotice(`Đang chạy ở chế độ xem độc lập (${err?.message || 'offline'})`);
  }
})();
