/**
 * Handles map visualization and interactions for GSV data
 * @class
 */
class MapVisualizer {
    /**
     * Create a new MapVisualizer instance
     */
    constructor() {
        /** @type {L.Map|null} Leaflet map instance */
        this.map = null;

        /** @type {L.CircleMarker[]} Array of map markers */
        this.markers = [];

        /** @type {L.LatLngBounds|null} Current map bounds */
        this.bounds = null;

        /** @type {L.Control|null} Legend control */
        this.legend = null;

        // Bind methods to maintain 'this' context
        this.onMarkerClick = this.onMarkerClick.bind(this);
        this.onMapClick = this.onMapClick.bind(this);
    }

    /**
     * Initialize or reinitialize the map
     * @throws {VisualizationError} If map initialization fails
     */
    initialize() {
        try {
            // Clean up existing map if it exists
            if (this.map) {
                this.cleanup();
            }

            // Create new map instance
            this.map = L.map('map', {
                center: CONFIG.map.defaultCenter,
                zoom: CONFIG.map.defaultZoom,
                minZoom: 2,
                maxZoom: 19,
                scrollWheelZoom: true
            });

            // Add tile layer
            this.addTileLayer();

            // Add event listeners
            this.setupEventListeners();

        } catch (error) {
            throw new VisualizationError('map initialization', error);
        }
    }

    /**
     * Add the map tile layer
     * @private
     * @throws {VisualizationError} If tile layer cannot be added
     */
    addTileLayer() {
        try {
            L.tileLayer(CONFIG.map.tileLayer.url, {
                attribution: CONFIG.map.tileLayer.attribution,
                maxZoom: 19,
                opacity: 0.8
            }).addTo(this.map);
        } catch (error) {
            throw new VisualizationError('tile layer', error);
        }
    }

    /**
     * Set up map event listeners
     * @private
     */
    setupEventListeners() {
        if (!this.map) {
            throw new VisualizationError('map not initialized');
        }

        this.map.on('click', this.onMapClick);
        this.map.on('zoomend', () => this.adjustMarkersToZoom());
        this.map.on('moveend', () => this.checkBoundaries());
    }

    /**
     * Clean up existing markers and controls
     */
    cleanup() {
        try {
            this.clearMarkers();
            if (this.legend) {
                this.legend.remove();
                this.legend = null;
            }
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        } catch (error) {
            console.error('Error during cleanup:', error);
            // Continue even if cleanup fails
        }
    }

    /**
     * Clear all markers from the map
     */
    clearMarkers() {
        try {
            this.markers.forEach(marker => {
                if (marker) {
                    marker.remove();
                }
            });
            this.markers = [];
        } catch (error) {
            throw new VisualizationError('clearing markers', error);
        }
    }

    /**
     * Get color for a marker based on age
     * @param {number} ageYears - Age in years
     * @param {number} maxAge - Maximum age in the dataset
     * @returns {string} HSL color string
     * @private
     */
    getColor(ageYears, maxAge) {
        if (typeof ageYears !== 'number' || typeof maxAge !== 'number') {
            throw new DataValidationError('Invalid age values for color calculation');
        }

        const { hue, saturation, minLightness, maxLightness } = CONFIG.visualization.colorScale;
        const lightness = Math.max(
            minLightness, 
            Math.min(maxLightness, maxLightness - (ageYears / maxAge) * (maxLightness - minLightness))
        );
        return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    }

    /**
     * Initialize map interactions
     * @private
     */
    initializeInteractions() {
        // Subscribe to date highlight events from histogram
        eventMediator.subscribe('dateHighlighted', (date) => {
            this.highlightMarkersForDate(date);
        });

        eventMediator.subscribe('highlightReset', () => {
            this.resetMarkerHighlight();
        });

        // Set up map click handler
        if (this.map) {
            this.map.on('click', (e) => {
                // Only reset if click is not on a marker or popup
                if (!e.originalEvent.target.closest('.leaflet-marker-icon') &&
                    !e.originalEvent.target.closest('.leaflet-popup')) {
                    eventMediator.publish('highlightReset');
                }
            });
        }
    }

    /**
     * Highlight markers for a specific date
     * @param {string} targetDate - Date to highlight (YYYY-MM format)
     * @private
     */
    highlightMarkersForDate(targetDate) {
        this.markers.forEach(marker => {
            const markerDate = marker.options.date;
            const isHighlighted = markerDate === targetDate;
            
            // Update marker appearance
            marker.setStyle({
                fillOpacity: isHighlighted ? 0.8 : 0.1,
                opacity: isHighlighted ? 1 : 0.1
            });

            // Bring highlighted markers to front
            if (isHighlighted) {
                marker.bringToFront();
            }
        });
    }

    /**
     * Reset marker highlighting
     * @private
     */
    resetMarkerHighlight() {
        this.markers.forEach(marker => {
            marker.setStyle({
                fillOpacity: 0.8,
                opacity: 1
            });
        });
    }

    /**
     * Add a marker to the map
     * @param {Object} row - Data row containing marker information
     * @param {number} maxAge - Maximum age in the dataset
     * @returns {L.CircleMarker} Created marker
     * @throws {VisualizationError} If marker cannot be created
     */
    addMarker(row, maxAge) {
        if (!this.map) {
            throw new VisualizationError('map not initialized');
        }

        try {
            this.validateMarkerData(row);

            const ageYears = DataLoader.calculateAgeYears(row.capture_date);
            const color = this.getColor(ageYears, maxAge);
            const dateStr = new Date(row.capture_date).toISOString().slice(0, 7);

            const marker = L.circleMarker(
                [row.pano_lat, row.pano_lon],
                {
                    radius: this.calculateMarkerRadius(),
                    color: color,
                    fillColor: color,
                    fillOpacity: CONFIG.visualization.markerOpacity,
                    weight: 1,
                    date: dateStr  // Store date for highlighting
                }
            );

            marker.bindPopup(this.createMarkerPopup(row, ageYears, dateStr));
            
            // Add click handler
            marker.on('click', () => {
                eventMediator.publish('dateHighlighted', dateStr);
            });

            marker.addTo(this.map);
            this.markers.push(marker);

            return marker;
        } catch (error) {
            throw new VisualizationError('marker creation', error);
        }
    }

    /**
     * Validate marker data
     * @param {Object} row - Data row to validate
     * @private
     * @throws {DataValidationError} If data is invalid
     */
    validateMarkerData(row) {
        if (!row || typeof row !== 'object') {
            throw new DataValidationError('Invalid marker data');
        }

        const required = ['pano_lat', 'pano_lon', 'capture_date', 'copyright_info', 'pano_id'];
        for (const field of required) {
            if (!(field in row)) {
                throw new DataValidationError(`Missing required field: ${field}`);
            }
        }

        if (!DataLoader.isValidCoordinate(row.pano_lat) || !DataLoader.isValidCoordinate(row.pano_lon)) {
            throw new DataValidationError('Invalid coordinates');
        }
    }

    /**
     * Create popup content for a marker
     * @param {Object} row - Data row
     * @param {number} ageYears - Age in years
     * @param {string} dateStr - Formatted date string
     * @returns {string} HTML content for popup
     * @private
     */
    createMarkerPopup(row, ageYears, dateStr) {
        return `
            <div class="marker-popup">
                <p><strong>Capture Date:</strong> ${dateStr}</p>
                <p><strong>Age:</strong> ${ageYears.toFixed(1)} years</p>
                <p><strong>Photographer:</strong> ${row.copyright_info}</p>
                <p><a href="https://www.google.com/maps/@?api=1&map_action=pano&pano=${row.pano_id}" 
                      target="_blank" rel="noopener noreferrer">View in GSV</a></p>
            </div>
        `;
    }

    /**
     * Calculate marker radius based on zoom level
     * @returns {number} Marker radius
     * @private
     */
    calculateMarkerRadius() {
        if (!this.map) return CONFIG.visualization.markerRadius;
        
        const zoom = this.map.getZoom();
        return Math.max(2, Math.min(8, zoom - 8));
    }

    /**
     * Adjust marker sizes based on current zoom level
     * @private
     */
    adjustMarkersToZoom() {
        const radius = this.calculateMarkerRadius();
        this.markers.forEach(marker => {
            marker.setRadius(radius);
        });
    }

    /**
     * Check and enforce map boundaries
     * @private
     */
    checkBoundaries() {
        if (this.map && this.bounds) {
            if (!this.bounds.contains(this.map.getCenter())) {
                this.map.panInsideBounds(this.bounds, { animate: true });
            }
        }
    }

    /**
     * Handle marker click events
     * @param {L.CircleMarker} marker - Clicked marker
     * @param {string} dateStr - Date string for the marker
     * @private
     */
    onMarkerClick(marker, dateStr) {
        // Custom click handling can be implemented here
        // For example, highlighting related markers or updating the histogram
    }

    /**
     * Handle map click events
     * @param {L.MouseEvent} e - Click event
     * @private
     */
    onMapClick(e) {
        // Close any open popups when clicking on the map
        if (this.map) {
            this.map.closePopup();
        }
    }

    /**
     * Fit map to data bounds
     * @param {Array} validData - Array of valid data points
     * @throws {VisualizationError} If bounds cannot be set
     */
    fitBounds(validData) {
        if (!this.map) {
            throw new VisualizationError('map not initialized');
        }

        try {
            const lats = validData.map(row => row.pano_lat);
            const lons = validData.map(row => row.pano_lon);
            
            this.bounds = L.latLngBounds(
                [Math.min(...lats), Math.min(...lons)],
                [Math.max(...lats), Math.max(...lons)]
            );

            // Add padding to bounds
            this.map.fitBounds(this.bounds, {
                padding: [50, 50],
                maxZoom: 15
            });
        } catch (error) {
            throw new VisualizationError('setting bounds', error);
        }
    }

    /**
     * Update the map legend
     * @param {number} maxAge - Maximum age in the dataset
     * @private
     */
    updateLegend(maxAge) {
        if (this.legend) {
            this.legend.remove();
        }

        this.legend = L.control({ position: 'bottomright' });
        this.legend.onAdd = () => {
            const div = L.DomUtil.create('div', 'info legend');
            const ages = [0, maxAge/4, maxAge/2, (3*maxAge)/4, maxAge];
            
            div.innerHTML = '<h4>Age (Years)</h4>';
            
            for (let i = 0; i < ages.length - 1; i++) {
                div.innerHTML += `
                    <div>
                        <i style="background:${this.getColor(ages[i], maxAge)}"></i>
                        ${Math.round(ages[i])} - ${Math.round(ages[i + 1])}
                    </div>
                `;
            }
            
            return div;
        };
        
        this.legend.addTo(this.map);
    }
}

// Export for use in other modules
export default MapVisualizer;