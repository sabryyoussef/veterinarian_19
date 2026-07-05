/** @odoo-module **/

// Simple JavaScript to add data-value attributes to badges
document.addEventListener('DOMContentLoaded', function() {
    function addBadgeDataAttributes() {
        // Find all badge elements in the tree view
        const badges = document.querySelectorAll('.o_list_view .o_field_badge, .o_list_view .badge');
        
        badges.forEach(badge => {
            const text = badge.textContent?.trim().toLowerCase();
            if (text && !badge.hasAttribute('data-value')) {
                // Set data-value attribute based on text content
                badge.setAttribute('data-value', text);
            }
        });
    }

    // Run initially
    addBadgeDataAttributes();

    // Watch for changes in the DOM (for dynamic content)
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'childList') {
                addBadgeDataAttributes();
            }
        });
    });

    // Start observing
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
});
