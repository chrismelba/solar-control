class SearchableSelect {
    constructor(inputId, optionsId, hiddenInputId) {
        this.input = document.getElementById(inputId);
        this.options = document.getElementById(optionsId);
        this.hiddenInput = document.getElementById(hiddenInputId);
        this.currentFocus = -1;
        
        this.setupEventListeners();
        this.setInitialValue();
    }

    setInitialValue() {
        const selectedOption = this.options.querySelector('[data-selected="true"]');
        if (selectedOption) {
            this.input.value = selectedOption.textContent;
        }
    }

    setupEventListeners() {
        this.input.addEventListener('focus', () => {
            this.options.classList.add('active');
        });

        this.input.addEventListener('input', () => {
            const searchText = this.input.value.toLowerCase();
            const optionElements = this.options.querySelectorAll('.option');
            
            optionElements.forEach(option => {
                const text = option.textContent.toLowerCase();
                option.style.display = text.includes(searchText) ? '' : 'none';
            });
            
            this.options.classList.add('active');
            this.currentFocus = -1;
        });

        this.input.addEventListener('keydown', (e) => {
            const optionElements = Array.from(this.options.querySelectorAll('.option:not([style*="display: none"])'));
            
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

        document.addEventListener('click', (e) => {
            if (!this.input.contains(e.target) && !this.options.contains(e.target)) {
                this.options.classList.remove('active');
            }
        });
    }

    addActive(optionElements) {
        if (!optionElements.length) return;
        
        // Remove active class from all options
        optionElements.forEach(opt => opt.classList.remove('active'));
        
        // Handle wrapping around
        if (this.currentFocus >= optionElements.length) this.currentFocus = 0;
        if (this.currentFocus < 0) this.currentFocus = optionElements.length - 1;
        
        // Add active class to current option
        const activeOption = optionElements[this.currentFocus];
        activeOption.classList.add('active');
        
        // Ensure the active option is visible
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
        this.input.value = option.textContent;
        this.hiddenInput.value = option.dataset.value;
        this.options.classList.remove('active');
        
        // Update selected state
        this.options.querySelectorAll('.option').forEach(opt => {
            opt.classList.remove('selected');
        });
        option.classList.add('selected');
    }
}

// Initialize all searchable selects on the page
document.addEventListener('DOMContentLoaded', function() {
    const searchableSelects = document.querySelectorAll('.searchable-select');
    searchableSelects.forEach(select => {
        const inputId = select.querySelector('input[type="text"]').id;
        const optionsId = select.querySelector('.options').id;
        const hiddenInputId = select.querySelector('input[type="hidden"]').id;
        new SearchableSelect(inputId, optionsId, hiddenInputId);
    });
}); 