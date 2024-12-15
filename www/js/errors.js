/**
 * Custom error classes for the application
 */

/**
 * Base error class for application-specific errors
 */
export class AppError extends Error {
    constructor(message, originalError = null) {
        super(message);
        this.name = this.constructor.name;
        this.originalError = originalError;
        this.timestamp = new Date();
    }

    getUserMessage() { 
        return this.message;
    }
}

/**
 * Error thrown when data loading fails
 */
export class DataLoadError extends AppError {
    constructor(resource, originalError = null) {
        super(`Failed to load ${resource}`, originalError);
        this.resource = resource;
    }
}

/**
 * Error thrown when data validation fails
 */
export class DataValidationError extends AppError {
    constructor(reason, invalidData = null) {
        super(`Data validation failed: ${reason}`);
        this.reason = reason;
        this.invalidData = invalidData;
    }
}

/**
 * Error thrown when visualization creation fails
 */
export class VisualizationError extends AppError {
    constructor(component, originalError = null) {
        super(`Failed to create ${component} visualization`, originalError);
        this.component = component;
    }
}

export class ErrorUI {
    constructor() {
        this.container = document.getElementById('error-container');
    }

    showError(message) {
        if (this.container) {
            this.container.innerHTML = `
                <div class="error-message">
                    ${message}
                </div>
            `;
            this.container.style.display = 'block';
        }
    }
}