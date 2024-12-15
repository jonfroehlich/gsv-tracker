/**
 * Main application class that coordinates all components
 * @class
 */
class App {
    /**
     * Initialize the application instance
     */
    constructor() {
        /** @type {MapVisualizer} Map visualization component */
        this.mapVisualizer = new MapVisualizer();
        
        /** @type {HistogramVisualizer} Histogram visualization component */
        this.histogramVisualizer = new HistogramVisualizer();
        
        /** @type {ErrorUI} Error handling UI component */
        this.errorUI = new ErrorUI();
        
        /** @type {Object|null} Currently loaded city data */
        this.currentCityData = null;

        // Bind methods to preserve 'this' context
        this.loadSelectedCity = this.loadSelectedCity.bind(this);
        this.handleError = this.handleError.bind(this);
    }

    /**
     * Initialize the application
     * @async
     * @throws {DataLoadError} If cities data fails to load
     */
    async initialize() {
        try {
            // Set up global error handling
            window.onerror = (msg, source, line, col, error) => {
                this.handleError(error || new Error(msg));
            };

            // Load cities data and populate selector
            const cities = await this.loadCitiesData();
            this.populateCitySelector(cities);
            
            // Initialize map
            this.mapVisualizer.initialize();
            
            // Set up event listeners
            this.setupEventListeners();
        } catch (error) {
            this.handleError(new AppError('Failed to initialize application', error));
        }
    }

    /**
     * Load cities data from the server
     * @async
     * @returns {Promise<Array>} Array of city data
     * @throws {DataLoadError} If the data fails to load
     */
    async loadCitiesData() {
        try {
            return await DataLoader.loadCities();
        } catch (error) {
            throw new DataLoadError('cities data', error);
        }
    }

    /**
     * Set up application event listeners
     * @private
     */
    setupEventListeners() {
        const citySelect = document.getElementById('citySelect');
        if (!citySelect) {
            throw new AppError('City select element not found');
        }

        citySelect.addEventListener('change', () => {
            try {
                this.updateLoadButtonState();
            } catch (error) {
                this.handleError(error);
            }
        });
    }

    /**
     * Handle errors in the application
     * @param {Error} error - The error to handle
     * @private
     */
    handleError(error) {
        console.error('Application error:', error);

        // Get user-friendly message
        let userMessage;
        if (error instanceof AppError) {
            userMessage = error.getUserMessage();
        } else {
            userMessage = 'An unexpected error occurred. Please try again later.';
        }

        // Show error to user
        this.errorUI.showError(userMessage);

        // Hide loading indicator if it's showing
        this.showLoading(false);
    }

    /**
     * Load and display data for the selected city
     * @async
     * @throws {DataLoadError} If the city data fails to load
     * @throws {DataValidationError} If the city data is invalid
     */
    async loadSelectedCity() {
        const select = document.getElementById('citySelect');
        const filename = select.value;
        const cityName = select.options[select.selectedIndex].text;
        
        if (!filename) {
            throw new DataValidationError('No city selected');
        }
        
        this.showLoading(true);
        
        try {
            // Load and validate data
            const rawData = await DataLoader.loadCityData(filename);
            this.validateCityData(rawData);

            const validData = DataLoader.filterValidData(rawData);
            if (validData.length === 0) {
                throw new DataValidationError('No valid data points found');
            }
            
            // Calculate statistics
            const stats = DataLoader.calculateStats(validData);
            
            // Update visualizations
            await this.updateVisualizations(validData, cityName, stats);
            
        } catch (error) {
            this.handleError(error);
        } finally {
            this.showLoading(false);
        }
    }

    /**
     * Validate loaded city data
     * @param {Object} data - The data to validate
     * @throws {DataValidationError} If the data is invalid
     * @private
     */
    validateCityData(data) {
        if (!Array.isArray(data)) {
            throw new DataValidationError('Data is not an array');
        }

        if (data.length === 0) {
            throw new DataValidationError('Data array is empty');
        }

        const requiredFields = ['status', 'pano_lat', 'pano_lon', 'capture_date', 'copyright_info'];
        const hasRequiredFields = data[0] && requiredFields.every(field => field in data[0]);
        
        if (!hasRequiredFields) {
            throw new DataValidationError('Data missing required fields');
        }
    }

    /**
     * Update all visualizations with new data
     * @param {Array} validData - The validated city data
     * @param {string} cityName - Name of the city
     * @param {Object} stats - Statistics about the data
     * @throws {VisualizationError} If visualization creation fails
     * @private
     */
    async updateVisualizations(validData, cityName, stats) {
        try {
            // Clear previous visualizations
            this.mapVisualizer.clearMarkers();
            
            // Find the maximum age for color scaling
            const maxAge = Math.max(...validData.map(row => 
                DataLoader.calculateAgeYears(row.capture_date)
            ));
            
            // Add markers to map
            try {
                validData.forEach(row => {
                    this.mapVisualizer.addMarker(row, maxAge);
                });
            } catch (error) {
                throw new VisualizationError('map markers', error);
            }
            
            // Fit map to bounds
            try {
                this.mapVisualizer.fitBounds(validData);
            } catch (error) {
                throw new VisualizationError('map bounds', error);
            }
            
            // Create histogram data
            const histogramData = this.createHistogramData(validData);
            
            // Update histogram
            try {
                this.histogramVisualizer.createHistogram(histogramData, cityName, maxAge);
            } catch (error) {
                throw new VisualizationError('histogram', error);
            }

            // Update statistics panel
            this.updateStatsPanel(stats, cityName);

            // Initialize interactions after creating visualizations
            this.mapVisualizer.initializeInteractions();
            this.histogramVisualizer.initializeInteractions();
        } catch (error) {
            throw new VisualizationError('visualizations', error);
        }
    }

    /**
     * Create histogram data from valid city data
     * @param {Array} validData - The validated city data
     * @returns {Object} Histogram data organized by date
     * @private
     */
    createHistogramData(validData) {
        try {
            const histogramData = {};
            validData.forEach(row => {
                const dateStr = new Date(row.capture_date).toISOString().slice(0, 7);
                histogramData[dateStr] = (histogramData[dateStr] || 0) + 1;
            });
            return histogramData;
        } catch (error) {
            throw new DataValidationError('Failed to create histogram data', error);
        }
    }

    /**
     * Update the statistics panel with new data
     * @param {Object} stats - Statistics about the data
     * @param {string} cityName - Name of the city
     * @private
     */
    updateStatsPanel(stats, cityName) {
        try {
            const panel = document.querySelector('.stats-panel') || this.createStatsPanel();
            
            panel.innerHTML = `
                <h3>${cityName} Statistics</h3>
                <p>Total Panoramas: ${stats.totalPanos.toLocaleString()}</p>
                <p>Average Age: ${stats.avgAge.toFixed(1)} years</p>
                <p>Median Age: ${stats.medianAge.toFixed(1)} years</p>
                <p>Date Range: ${stats.oldestDate.toLocaleDateString()} to ${stats.newestDate.toLocaleDateString()}</p>
            `;
        } catch (error) {
            throw new VisualizationError('statistics panel', error);
        }
    }

    /**
     * Create the statistics panel if it doesn't exist
     * @returns {HTMLElement} The statistics panel element
     * @private
     */
    createStatsPanel() {
        const panel = document.createElement('div');
        panel.className = 'overlay-panel stats-panel';
        document.body.appendChild(panel);
        return panel;
    }

    /**
     * Populate the city selector with available cities
     * @param {Array} cities - Array of city data
     * @private
     */
    populateCitySelector(cities) {
        try {
            const select = document.getElementById('citySelect');
            if (!select) {
                throw new AppError('City select element not found');
            }

            select.innerHTML = '<option value="">Select a city...</option>';
            
            cities.forEach(city => {
                const option = document.createElement('option');
                option.value = city.filename;
                const location = [
                    city.name,
                    city.state,
                    city.country
                ].filter(Boolean).join(', ');
                option.textContent = location;
                select.appendChild(option);
            });
        } catch (error) {
            throw new AppError('Failed to populate city selector', error);
        }
    }

    /**
     * Update the state of the load button based on selection
     * @private
     */
    updateLoadButtonState() {
        try {
            const button = document.querySelector('#citySelector button');
            const select = document.getElementById('citySelect');
            if (!button || !select) {
                throw new AppError('Required elements not found');
            }
            button.disabled = !select.value;
        } catch (error) {
            throw new AppError('Failed to update button state', error);
        }
    }

    /**
     * Show or hide the loading indicator
     * @param {boolean} show - Whether to show the loading indicator
     * @private
     */
    showLoading(show) {
        try {
            const loading = document.getElementById('loading');
            if (!loading) {
                throw new AppError('Loading element not found');
            }
            loading.style.display = show ? 'flex' : 'none';
        } catch (error) {
            console.error('Failed to toggle loading state:', error);
            // Don't throw here as this is not critical to application function
        }
    }
}

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    const app = new App();
    
    // Initialize with error handling
    app.initialize().catch(error => {
        console.error('Failed to initialize application:', error);
        const errorUI = new ErrorUI();
        errorUI.showError('Failed to initialize application. Please refresh the page.');
    });
    
    // Make loadSelectedCity available globally for the button onclick handler
    window.loadSelectedCity = () => {
        try {
            return app.loadSelectedCity();
        } catch (error) {
            app.handleError(error);
        }
    };
});

// Export for use in other modules if needed
export default App;