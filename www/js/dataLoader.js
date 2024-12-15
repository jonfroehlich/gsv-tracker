import CONFIG from './config.js';
import { AppError, DataLoadError, DataValidationError } from './errors.js';

/**
 * Handles all data loading and processing operations for the application
 * @class
 */
class DataLoader {
    /**
     * Load available cities data from the configuration endpoint
     * @async
     * @returns {Promise<Array>} Array of city metadata
     * @throws {DataLoadError} If cities data cannot be loaded
     */
    static async loadCities() {
        try {
            console.log('Starting to load cities data...');
            const url = CONFIG.urls.getCitiesJson();
            
            console.log('Fetching from:', url);
            const response = await fetch(url);
            
            if (!response.ok) {
                console.error('Failed to fetch cities:', response.status, response.statusText);
                throw new DataLoadError('cities data', 
                    `HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            console.log('Cities data received:', data);  // See the actual data
            
            // Validate the cities data structure
            if (!data || !Array.isArray(data.cities)) {
                console.error('Invalid data structure received:', data);
                throw new DataValidationError('Invalid cities data format');
            }
            
            console.log(`Successfully loaded ${data.cities.length} cities`);
            return data.cities;
        } catch (error) {
            console.error('Error in loadCities:', error);
            if (error instanceof AppError) {
                throw error;
            }
            throw new DataLoadError('cities data', error);
        }
    }

    /**
     * Load and decompress city data from a gzipped CSV file
     * @async
     * @param {string} filename - Name of the city data file
     * @returns {Promise<Array>} Array of city data points
     * @throws {DataLoadError} If city data cannot be loaded
     * @throws {DataValidationError} If data is invalid
     */
    static async loadCityData(filename) {
        if (!filename) {
            throw new DataValidationError('Filename is required');
        }

        try {
            // Load compressed data
            const response = await fetch(CONFIG.urls.getCityData(filename));
            
            if (!response.ok) {
                throw new DataLoadError(`city data (${filename})`, 
                    `HTTP error! status: ${response.status}`);
            }

            // Get array buffer for decompression
            const compressedData = await response.arrayBuffer();
            if (!compressedData || compressedData.byteLength === 0) {
                throw new DataValidationError('Empty compressed data received');
            }

            // Decompress data
            const decompressed = await this.decompressData(compressedData);
            
            // Parse CSV
            return await this.parseCSV(decompressed);
        } catch (error) {
            if (error instanceof AppError) {
                throw error;
            }
            throw new DataLoadError(`city data (${filename})`, error);
        }
    }

    /**
     * Decompress gzipped data
     * @private
     * @param {ArrayBuffer} compressedData - The compressed data
     * @returns {Promise<string>} Decompressed string data
     * @throws {DataValidationError} If decompression fails
     */
    static async decompressData(compressedData) {
        try {
            const decompressed = pako.inflate(new Uint8Array(compressedData), { to: 'string' });
            if (!decompressed) {
                throw new Error('Decompression resulted in empty data');
            }
            return decompressed;
        } catch (error) {
            throw new DataValidationError('Failed to decompress data', error);
        }
    }

    /**
     * Parse CSV string into structured data
     * @private
     * @param {string} csvData - The CSV string to parse
     * @returns {Promise<Array>} Parsed CSV data
     * @throws {DataValidationError} If parsing fails
     */
    static parseCSV(csvData) {
        if (!csvData || typeof csvData !== 'string') {
            throw new DataValidationError('Invalid CSV data');
        }

        return new Promise((resolve, reject) => {
            Papa.parse(csvData, {
                header: true,
                dynamicTyping: true,
                skipEmptyLines: true,
                complete: (results) => {
                    if (results.errors && results.errors.length > 0) {
                        reject(new DataValidationError(
                            'CSV parsing errors', 
                            results.errors
                        ));
                        return;
                    }
                    resolve(results.data);
                },
                error: (error) => {
                    reject(new DataValidationError('CSV parsing failed', error));
                }
            });
        });
    }

    /**
     * Filter valid data points from raw data
     * @param {Array} data - Raw data points to filter
     * @returns {Array} Filtered valid data points
     * @throws {DataValidationError} If data is invalid
     */
    static filterValidData(data) {
        if (!Array.isArray(data)) {
            throw new DataValidationError('Data must be an array');
        }

        try {
            return data.filter(row => 
                row &&
                row.status === 'OK' &&
                this.isValidCoordinate(row.pano_lat) &&
                this.isValidCoordinate(row.pano_lon) &&
                this.isValidDate(row.capture_date) &&
                row.copyright_info?.includes('Google')
            );
        } catch (error) {
            throw new DataValidationError('Error filtering data', error);
        }
    }

    /**
     * Check if a coordinate value is valid
     * @private
     * @param {number} coord - Coordinate value to check
     * @returns {boolean} Whether the coordinate is valid
     */
    static isValidCoordinate(coord) {
        return typeof coord === 'number' && 
               !isNaN(coord) && 
               isFinite(coord) &&
               coord >= -180 && 
               coord <= 180;
    }

    /**
     * Check if a date string is valid
     * @private
     * @param {string} dateStr - Date string to check
     * @returns {boolean} Whether the date is valid
     */
    static isValidDate(dateStr) {
        if (!dateStr) return false;
        const date = new Date(dateStr);
        return date instanceof Date && !isNaN(date);
    }

    /**
     * Calculate statistics for the data
     * @param {Array} validData - Validated data points
     * @returns {Object} Statistics about the data
     * @throws {DataValidationError} If statistics cannot be calculated
     */
    static calculateStats(validData) {
        if (!Array.isArray(validData) || validData.length === 0) {
            throw new DataValidationError('Invalid or empty data for statistics');
        }

        try {
            const now = new Date();
            const ages = validData.map(row => this.calculateAgeYears(row.capture_date));
            
            // Sort ages for median calculation
            const sortedAges = [...ages].sort((a, b) => a - b);
            
            return {
                totalPanos: validData.length,
                avgAge: ages.reduce((a, b) => a + b) / ages.length,
                medianAge: sortedAges[Math.floor(sortedAges.length / 2)],
                oldestDate: new Date(Math.min(...validData.map(row => new Date(row.capture_date)))),
                newestDate: new Date(Math.max(...validData.map(row => new Date(row.capture_date)))),
                coverageArea: this.calculateCoverageArea(validData)
            };
        } catch (error) {
            throw new DataValidationError('Failed to calculate statistics', error);
        }
    }

    /**
     * Calculate age in years from a date
     * @param {string} dateStr - Date string to calculate age from
     * @returns {number} Age in years
     * @throws {DataValidationError} If age cannot be calculated
     */
    static calculateAgeYears(dateStr) {
        if (!this.isValidDate(dateStr)) {
            throw new DataValidationError('Invalid date for age calculation');
        }

        const date = new Date(dateStr);
        const now = new Date();
        return (now - date) / (1000 * 60 * 60 * 24 * 365.25);
    }

    /**
     * Calculate the coverage area of the data points
     * @private
     * @param {Array} validData - Validated data points
     * @returns {Object} Coverage area statistics
     */
    static calculateCoverageArea(validData) {
        const lats = validData.map(row => row.pano_lat);
        const lons = validData.map(row => row.pano_lon);
        
        return {
            minLat: Math.min(...lats),
            maxLat: Math.max(...lats),
            minLon: Math.min(...lons),
            maxLon: Math.max(...lons)
        };
    }
}

// Export for use in other modules
export default DataLoader;