/**
 * Event mediator for coordinating visualization interactions
 */
class EventMediator {
    constructor() {
        this.subscribers = new Map();
    }

    /**
     * Subscribe to an event
     * @param {string} event - Event name
     * @param {Function} callback - Callback function
     */
    subscribe(event, callback) {
        if (!this.subscribers.has(event)) {
            this.subscribers.set(event, new Set());
        }
        this.subscribers.get(event).add(callback);
    }

    /**
     * Publish an event
     * @param {string} event - Event name
     * @param {any} data - Event data
     */
    publish(event, data) {
        if (this.subscribers.has(event)) {
            this.subscribers.get(event).forEach(callback => callback(data));
        }
    }
}

// Create a singleton instance
export const eventMediator = new EventMediator();