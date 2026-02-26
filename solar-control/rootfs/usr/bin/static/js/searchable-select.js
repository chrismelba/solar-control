class SearchableSelect {
    // Single shared document click handler registered once for all instances
    static _instances = [];
    static _instanceMap = new Map();
    static _documentHandlerRegistered = false;

    static _registerDocumentHandler() {
        if (SearchableSelect._documentHandlerRegistered) return;
        document.addEventListener('click', (e) => {
            SearchableSelect._instances.forEach(instance => {
                if (!instance.input.contains(e.target) && !instance.options.contains(e.target)) {
                    instance.options.classList.remove('active');
                }
            });
        });
        SearchableSelect._documentHandlerRegistered = true;
    }

    // Returns existing instance for inputId if one exists, otherwise creates a new one.
    // Use this instead of `new SearchableSelect(...)` to prevent double-init.
    static getOrCreate(inputId, optionsId, hiddenInputId) {
        if (SearchableSelect._instanceMap.has(inputId)) {
            return SearchableSelect._instanceMap.get(inputId);
        }
        return new SearchableSelect(inputId, optionsId, hiddenInputId);
    }

    constructor(inputId, optionsId, hiddenInputId) {
        this.input = document.getElementById(inputId);
        this.options = document.getElementById(optionsId);
        this.hiddenInput = document.getElementById(hiddenInputId);
        this.onSelectCallback = null;
        this.currentFocus = -1;
        this._showingAll = false;

        SearchableSelect._instances.push(this);
        SearchableSelect._instanceMap.set(inputId, this);
        SearchableSelect._registerDocumentHandler();

        this.setupEventListeners();
        this.setInitialValue();
    }

    setInitialValue() {
        const selectedOption = this.options.querySelector('[data-selected="true"]');
        if (selectedOption) {
            if (selectedOption.hasAttribute('data-extended')) {
                this._showAll();
            }
            this.input.value = selectedOption.textContent.trim();
            if (this.onSelectCallback) {
                this.onSelectCallback(selectedOption.dataset.value, selectedOption.textContent.trim());
            }
        }
    }

    _debounce(fn, delay) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    _visibleOptions() {
        return Array.from(this.options.querySelectorAll('.option')).filter(o => o.style.display !== 'none');
    }

    _showAll() {
        this._showingAll = true;
        this.options.querySelectorAll('[data-extended]').forEach(opt => {
            opt.style.display = '';
        });
        const footer = this.options.querySelector('.options-footer');
        if (footer) footer.style.display = 'none';
    }

    setupEventListeners() {
        // Wire "Show all" footer button before other events
        const showAllBtn = this.options.querySelector('.options-show-all');
        if (showAllBtn) {
            showAllBtn.addEventListener('click', () => {
                this._showAll();
                this.options.classList.add('active');
            });
        }

        this.input.addEventListener('focus', () => {
            this.options.classList.add('active');
        });

        this.input.addEventListener('input', this._debounce(() => {
            const searchText = this.input.value.toLowerCase();
            const footer = this.options.querySelector('.options-footer');

            if (searchText === '') {
                // Reset to primary-only view unless "Show all" was clicked
                this.options.querySelectorAll('.option').forEach(option => {
                    if (option.hasAttribute('data-extended') && !this._showingAll) {
                        option.style.display = 'none';
                    } else {
                        option.style.display = '';
                    }
                });
                if (footer && !this._showingAll) footer.style.display = '';
            } else {
                // Search across all options including extended; hide footer
                this.options.querySelectorAll('.option').forEach(option => {
                    const text = option.textContent.toLowerCase();
                    option.style.display = text.includes(searchText) ? '' : 'none';
                });
                if (footer) footer.style.display = 'none';
            }

            this.options.classList.add('active');
            this.currentFocus = -1;
        }, 150));

        this.input.addEventListener('keydown', (e) => {
            const optionElements = this._visibleOptions();

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                e.stopPropagation();
                this.currentFocus++;
                this.addActive(optionElements);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                e.stopPropagation();
                this.currentFocus--;
                this.addActive(optionElements);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                e.stopPropagation();
                const activeOption = this.options.querySelector('.option.active');
                if (activeOption) {
                    this.selectOption(activeOption);
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                this.options.classList.remove('active');
            }
        });

        this.options.addEventListener('click', (e) => {
            const option = e.target.closest('.option');
            if (option) {
                this.selectOption(option);
            }
        });
    }

    addActive(optionElements) {
        if (!optionElements.length) return;

        optionElements.forEach(opt => opt.classList.remove('active'));

        if (this.currentFocus >= optionElements.length) this.currentFocus = 0;
        if (this.currentFocus < 0) this.currentFocus = optionElements.length - 1;

        const activeOption = optionElements[this.currentFocus];
        activeOption.classList.add('active');

        const optionsContainer = this.options;
        const optionTop = activeOption.offsetTop;
        const optionBottom = optionTop + activeOption.offsetHeight;
        const containerTop = optionsContainer.scrollTop;
        const containerBottom = containerTop + optionsContainer.offsetHeight;

        if (optionTop < containerTop) {
            optionsContainer.scrollTop = optionTop;
        } else if (optionBottom > containerBottom) {
            optionsContainer.scrollTop = optionBottom - optionsContainer.offsetHeight;
        }
    }

    selectOption(option) {
        this.input.value = option.textContent.trim();
        this.hiddenInput.value = option.dataset.value;
        this.options.classList.remove('active');

        this.options.querySelectorAll('.option').forEach(opt => {
            opt.classList.remove('selected');
        });
        option.classList.add('selected');

        if (this.onSelectCallback) {
            this.onSelectCallback(option.dataset.value, option.textContent.trim());
        }
    }
}

// Auto-initialize all searchable selects on the page.
// Uses getOrCreate so manual inits in page scripts don't create duplicates.
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.searchable-select').forEach(select => {
        const inputEl = select.querySelector('input[type="text"]');
        const optionsEl = select.querySelector('.options');
        const hiddenEl = select.querySelector('input[type="hidden"]');
        if (inputEl && optionsEl && hiddenEl) {
            SearchableSelect.getOrCreate(inputEl.id, optionsEl.id, hiddenEl.id);
        }
    });
});
