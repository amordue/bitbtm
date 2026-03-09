document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-lightbox-src]');
    if (trigger) {
        const panel = trigger.closest('[id^="robot-panel-"]');
        if (!panel) {
            return;
        }
        const lightbox = panel.querySelector('.robot-lightbox');
        const image = lightbox ? lightbox.querySelector('.robot-lightbox-image') : null;
        const caption = lightbox ? lightbox.querySelector('.robot-lightbox-caption') : null;
        if (!lightbox || !image) {
            return;
        }
        image.src = trigger.dataset.lightboxSrc || '';
        image.alt = trigger.dataset.lightboxAlt || '';
        if (caption) {
            caption.textContent = trigger.dataset.lightboxCaption || '';
        }
        lightbox.hidden = false;
        document.body.style.overflow = 'hidden';
        return;
    }

    const closeButton = event.target.closest('[data-lightbox-close]');
    const overlay = event.target.classList && event.target.classList.contains('robot-lightbox')
        ? event.target
        : null;
    const lightbox = closeButton ? closeButton.closest('.robot-lightbox') : overlay;
    if (lightbox) {
        lightbox.hidden = true;
        document.body.style.overflow = '';
    }
});

document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
        return;
    }
    document.querySelectorAll('.robot-lightbox').forEach(function (lightbox) {
        lightbox.hidden = true;
    });
    document.body.style.overflow = '';
});