// ============================================================
// KALLYAS - Business Agency Website
// JavaScript File
// ============================================================

document.addEventListener('DOMContentLoaded', function () {

    // ---- 1. Navbar: Add "scrolled" class on scroll ----
    const navbar = document.getElementById('mainNav');

    window.addEventListener('scroll', function () {
        if (window.scrollY > 60) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });


    // ---- 2. Active nav link on scroll ----
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-link');

    function highlightNav() {
        let scrollPos = window.scrollY + 100;
        sections.forEach(section => {
            if (
                scrollPos >= section.offsetTop &&
                scrollPos < section.offsetTop + section.offsetHeight
            ) {
                navLinks.forEach(link => link.classList.remove('active'));
                const active = document.querySelector('.nav-link[href="#' + section.id + '"]');
                if (active) active.classList.add('active');
            }
        });
    }

    window.addEventListener('scroll', highlightNav);


    // ---- 3. Portfolio Filter ----
    const filterBtns = document.querySelectorAll('.pf-btn');
    const portfolioItems = document.querySelectorAll('.portfolio-item');

    filterBtns.forEach(btn => {
        btn.addEventListener('click', function () {
            // Update active button
            filterBtns.forEach(b => b.classList.remove('active'));
            this.classList.add('active');

            const filter = this.getAttribute('data-filter');

            portfolioItems.forEach(item => {
                if (filter === 'all' || item.getAttribute('data-category') === filter) {
                    item.classList.remove('hidden');
                    item.style.animation = 'fadeIn 0.4s ease';
                } else {
                    item.classList.add('hidden');
                }
            });
        });
    });


    // ---- 4. Contact Form Submission ----
    const contactForm = document.getElementById('contactForm');
    if (contactForm) {
        contactForm.addEventListener('submit', function (e) {
            e.preventDefault();
            showToast('Message sent successfully! We will get back to you soon.', 'success');
            contactForm.reset();
        });
    }


    // ---- 5. Newsletter Form ----
    const newsletterForm = document.getElementById('newsletterForm');
    if (newsletterForm) {
        newsletterForm.addEventListener('submit', function (e) {
            e.preventDefault();
            showToast('You have subscribed to our newsletter!', 'success');
            newsletterForm.reset();
        });
    }


    // ---- 6. Simple Toast Notification ----
    function showToast(message, type) {
        // Remove any existing toast
        const existing = document.querySelector('.toast-notify');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = 'toast-notify';
        toast.innerHTML = message;
        toast.style.cssText = `
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: ${type === 'success' ? '#27ae60' : '#e74c3c'};
            color: white;
            padding: 14px 24px;
            border-radius: 4px;
            font-family: 'Poppins', sans-serif;
            font-size: 0.88rem;
            font-weight: 500;
            z-index: 9999;
            box-shadow: 0 6px 20px rgba(0,0,0,0.25);
            animation: slideInRight 0.4s ease;
            max-width: 320px;
        `;

        // Add animation keyframes once
        if (!document.getElementById('toast-styles')) {
            const style = document.createElement('style');
            style.id = 'toast-styles';
            style.textContent = `
                @keyframes slideInRight {
                    from { transform: translateX(120%); opacity: 0; }
                    to   { transform: translateX(0);    opacity: 1; }
                }
                @keyframes fadeIn {
                    from { opacity: 0; transform: scale(0.95); }
                    to   { opacity: 1; transform: scale(1); }
                }
            `;
            document.head.appendChild(style);
        }

        document.body.appendChild(toast);

        // Auto-remove after 3.5 seconds
        setTimeout(() => {
            toast.style.transition = 'opacity 0.4s';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 400);
        }, 3500);
    }


    // ---- 7. Smooth scroll for anchor links ----
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                e.preventDefault();
                const offset = 80; // navbar height
                const top = target.getBoundingClientRect().top + window.scrollY - offset;
                window.scrollTo({ top: top, behavior: 'smooth' });

                // Close mobile navbar if open
                const navCollapse = document.getElementById('navbarNav');
                if (navCollapse && navCollapse.classList.contains('show')) {
                    navCollapse.classList.remove('show');
                }
            }
        });
    });

});
