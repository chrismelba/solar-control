class SearchableSelect {
    constructor(inputId, optionsId, hiddenInputId) {
        this.input = document.getElementById(inputId);
        this.options = document.getElementById(optionsId);
        this.hiddenInput = document.getElementById(hiddenInputId);
        
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
        });

        this.options.addEventListener('click', (e) => {
            const option = e.target.closest('.option');
            if (option) {
                this.input.value = option.textContent;
                this.hiddenInput.value = option.dataset.value;
                this.options.classList.remove('active');
                
                // Update selected state
                this.options.querySelectorAll('.option').forEach(opt => {
                    opt.classList.remove('selected');
                });
                option.classList.add('selected');
            }
        });

        document.addEventListener('click', (e) => {
            if (!this.input.contains(e.target) && !this.options.contains(e.target)) {
                this.options.classList.remove('active');
            }
        });
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