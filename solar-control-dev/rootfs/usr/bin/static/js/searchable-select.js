class SearchableSelect {
    // Single shared document click handler registered once for all instances
    static _instances = [];
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

    constructor(inputId, optionsId, hiddenInputId) {
        this.input = document.getElementById(inputId);
        this.options = document.getElementById(optionsId);
        this.hiddenInput = document.getElementById(hiddenInputId);
        this.onSelectCallback = null;
        this.currentFocus = -1;

        SearchableSelect._instances.push(this);
        SearchableSelect._registerDocumentHandler();

        this.setupEventListeners();
        this.setInitialValue();
    }

    setInitialValue() {
        const selectedOption = this.options.querySelector('[data-selected="true"]');
        if (selectedOption) {
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

    setupEventListeners() {
        this.input.addEventListener('focus', () => {
            this.options.classList.add('active');
        });

        this.input.addEventListener('input', this._debounce(() => {
            const searchText = this.input.value.toLowerCase();
            this.options.querySelectorAll('.option').forEach(option => {
                const text = option.textContent.toLowerCase();
                option.style.display = text.includes(searchText) ? '' : 'none';
            });
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

// Initialize all searchable selects on the page
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.searchable-select').forEach(select => {
        const inputId = select.querySelector('input[type="text"]').id;
        const optionsId = select.querySelector('.options').id;
        const hiddenInputId = select.querySelector('input[type="hidden"]').id;
        new SearchableSelect(inputId, optionsId, hiddenInputId);
    });
});
