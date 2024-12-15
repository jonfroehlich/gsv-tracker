import CONFIG from './config.js';
import { eventMediator } from './events.js';
import DataLoader from './dataLoader.js';

/**
 * Handles the histogram visualization and interactions
 * @class
 */
class HistogramVisualizer {
    /**
     * Create a new HistogramVisualizer instance
     */
    constructor() {
        /** @type {Chart|null} Chart.js instance */
        this.chart = null;
        
        /** @type {HTMLElement|null} Container element */
        this.container = null;
        
        /** @type {HTMLElement|null} Content wrapper element */
        this.contentWrapper = null;

        /** @type {number} Minimum width for the histogram */
        this.minWidth = 300;
        
        /** @type {number} Width per bar in pixels */
        this.widthPerBar = 30;
        
        /** @type {number} Maximum width as percentage of viewport */
        this.maxWidthPercent = 80;

        // Bind methods to maintain 'this' context
        this.toggleMinimize = this.toggleMinimize.bind(this);
    }

    /**
     * Initialize or reinitialize the histogram
     * @throws {VisualizationError} If initialization fails
     */
    initialize() {
        try {
            if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }

            if (this.container) {
                this.container.remove();
                this.container = null;
            }

            this.createContainer();
        } catch (error) {
            throw new VisualizationError('histogram initialization', error);
        }
    }

    /**
     * Create the container structure for the histogram
     * @private
     */
    createContainer() {
        // Create main container
        this.container = document.createElement('div');
        this.container.className = 'overlay-panel histogram-container';
        
        // Create header with title and minimize button
        const header = document.createElement('div');
        header.className = 'histogram-header';
        header.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            position: sticky;
            top: 0;
            background: rgba(255, 255, 255, 0.9);
            z-index: 1;
        `;
        
        // Create title element
        this.titleElement = document.createElement('h3');
        this.titleElement.className = 'histogram-title';
        header.appendChild(this.titleElement);

        // Create minimize button
        const minimizeButton = document.createElement('button');
        minimizeButton.className = 'minimize-button';
        minimizeButton.innerHTML = '−';
        minimizeButton.style.cssText = `
            background: none;
            border: none;
            cursor: pointer;
            font-size: 20px;
            padding: 5px 10px;
            color: #666;
        `;
        minimizeButton.onclick = this.toggleMinimize;
        header.appendChild(minimizeButton);

        // Create content wrapper
        this.contentWrapper = document.createElement('div');
        this.contentWrapper.className = 'histogram-content';
        this.contentWrapper.style.cssText = `
            transition: height 0.3s ease;
            overflow-x: auto;
        `;

        // Add elements to container
        this.container.appendChild(header);
        this.container.appendChild(this.contentWrapper);
        
        document.body.appendChild(this.container);
    }

    /**
     * Toggle minimize/expand state of the histogram
     * @private
     */
    toggleMinimize() {
        if (!this.container || !this.contentWrapper) return;

        const isMinimized = this.container.classList.contains('minimized');
        const button = this.container.querySelector('.minimize-button');
        
        if (isMinimized) {
            // Expand
            this.container.classList.remove('minimized');
            this.contentWrapper.style.height = '150px';
            button.innerHTML = '−';
        } else {
            // Minimize
            this.container.classList.add('minimized');
            this.contentWrapper.style.height = '0';
            button.innerHTML = '+';
        }
    }

    /**
     * Calculate appropriate width for the histogram
     * @param {number} dataPoints - Number of data points
     * @returns {number} Calculated width in pixels
     * @private
     */
    calculateWidth(dataPoints) {
        const viewportWidth = window.innerWidth;
        const maxWidth = (viewportWidth * this.maxWidthPercent) / 100;
        const calculatedWidth = Math.max(
            this.minWidth, 
            dataPoints * this.widthPerBar
        );
        return Math.min(calculatedWidth, maxWidth);
    }

    /**
     * Create or update the histogram visualization
     * @param {Object} histogramData - Data for the histogram
     * @param {string} cityName - Name of the city being visualized
     * @param {number} maxAge - Maximum age in the dataset
     * @throws {VisualizationError} If histogram creation fails
     */
    createHistogram(histogramData, cityName, maxAge) {
        try {
            this.initialize();
            
            // Update title
            this.titleElement.textContent = `${cityName}: GSV Coverage Over Time`;

            // Create canvas for Chart.js
            const canvas = document.createElement('canvas');
            canvas.id = 'histogramCanvas';
            this.contentWrapper.appendChild(canvas);

            // Calculate appropriate width
            const numBars = Object.keys(histogramData).length;
            const width = this.calculateWidth(numBars);
            
            // Set content wrapper width
            this.contentWrapper.style.width = `${width}px`;
            this.contentWrapper.style.height = '150px';

            // Prepare data for Chart.js
            const sortedDates = Object.keys(histogramData).sort();
            const data = sortedDates.map(date => histogramData[date]);
            const maxValue = Math.max(...data);

            // Create Chart.js instance
            this.chart = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: sortedDates,
                    datasets: [{
                        data: data,
                        backgroundColor: sortedDates.map(date => {
                            const ageYears = DataLoader.calculateAgeYears(date);
                            return this.getColor(ageYears, maxAge);
                        }),
                        borderColor: 'rgba(0,0,0,0.2)',
                        borderWidth: 1
                    }]
                },
                options: this.getChartOptions(maxValue)
            });

            // Position the container
            this.positionContainer(width);

        } catch (error) {
            throw new VisualizationError('histogram creation', error);
        }
    }

    /** 
    * Initialize histogram interactions
    * @private
    */
    initializeInteractions() {
        // Subscribe to date highlight events from map
        eventMediator.subscribe('dateHighlighted', (date) => {
            this.highlightDate(date);
        });

        eventMediator.subscribe('highlightReset', () => {
            this.resetHighlight();
        });
    }

    /**
    * Highlight bars for a specific date
    * @param {string} targetDate - Date to highlight (YYYY-MM format)
    * @private
    */
    highlightDate(targetDate) {
        if (!this.chart) return;

        const fadeOpacity = 0.2;
        this.chart.data.datasets[0].backgroundColor = this.chart.data.labels.map(date => {
            const color = this.getColor(
                DataLoader.calculateAgeYears(date), 
                this.maxAge
            );
            return date === targetDate ? color : this.fadeColor(color, fadeOpacity);
        });

        this.chart.update('none'); // Update without animation
    }

    /**
    * Reset highlight state
    * @private
    */
    resetHighlight() {
        if (!this.chart) return;

        this.chart.data.datasets[0].backgroundColor = this.chart.data.labels.map(date => 
            this.getColor(DataLoader.calculateAgeYears(date), this.maxAge)
        );

        this.chart.update('none');
    }

    /**
     * Get Chart.js configuration options
     * @param {number} maxValue - Maximum value in the dataset
     * @returns {Object} Chart.js options
     * @private
     */
    getChartOptions(maxValue) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        title: (tooltipItems) => `Date: ${tooltipItems[0].label}`,
                        label: (context) => `Count: ${context.raw}`
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    suggestedMax: maxValue * 1.1,
                    title: {
                        display: true,
                        text: 'GSV Images'
                    },
                    ticks: {
                        maxTicksLimit: 8
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Capture Date'
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45,
                        autoSkip: true,
                        maxTicksLimit: 20
                    }
                }
            },
            animation: {
                duration: 500
            },
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index;
                    const date = this.chart.data.labels[index];
                    eventMediator.publish('dateHighlighted', date);
                } else {
                    eventMediator.publish('highlightReset');
                }
            }
        };
    }

    /**
     * Position the histogram container
     * @param {number} width - Width of the histogram
     * @private
     */
    positionContainer(width) {
        if (!this.container) return;

        const viewportWidth = window.innerWidth;
        const margin = 20;
        
        // If histogram is wider than minimum width, adjust position
        if (width > this.minWidth) {
            const right = margin;
            const bottom = margin;
            
            Object.assign(this.container.style, {
                right: `${right}px`,
                bottom: `${bottom}px`,
                maxHeight: '80vh'
            });
        }
    }

    /**
     * Get color for a bar based on age
     * @param {number} ageYears - Age in years
     * @param {number} maxAge - Maximum age in the dataset
     * @returns {string} HSL color string
     * @private
     */
    getColor(ageYears, maxAge) {
        const { hue, saturation, minLightness, maxLightness } = CONFIG.visualization.colorScale;
        const lightness = Math.max(
            minLightness, 
            Math.min(maxLightness, maxLightness - (ageYears / maxAge) * (maxLightness - minLightness))
        );
        return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    }
}

// Export for use in other modules
export default HistogramVisualizer;