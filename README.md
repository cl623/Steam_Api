# Steam Market History Collector WIP

## Overview
The Steam Market History Collector is a Python script designed to collect and store price history data for items in the Steam Community Market. It supports multiple games and implements rate limiting, data validation, and efficient batch processing.

## Use
Download files
app.py -> Update STEAMAPIS_KEY and steamLoginSecure variables with your personal values (if you want to see price history data)
run python app.py


<img width="1918" height="993" alt="image" src="https://github.com/user-attachments/assets/feac2b6f-99b4-4129-a612-e8c11950aca6" />


## Goals
1. **Data Collection**
   - Collect market listings and price history for Steam market items
   - Support multiple games simultaneously
   - Maintain historical price data for market analysis

2. **Rate Limit Compliance**
   - Respect Steam's API rate limits
   - Implement per-game rate limiting
   - Handle rate limit errors gracefully

3. **Data Quality**
   - Validate price history data
   - Detect and handle anomalous prices
   - Ensure data consistency and reliability

4. **Efficient Processing**
   - Process items in batches
   - Balance workload between games
   - Optimize database operations

## Requirements

### Batch Processing
- Total batch size: 100 items
- Items per game: 50 items (with 2 games)
- Page size: 10 items per API request
- Pages per game: 5 pages (50 items)

### Rate Limits
- Per minute: 10 requests
- Per day: 1000 requests
- Implement exponential backoff for rate limit errors
- Minimum delay between requests: 2-4 seconds

### Data Validation
- Minimum price history entries: 5
- Maximum price deviation: 50%
- Validate data before storage
- Track and handle failed items

### Database Structure
- Items table:
  - market_hash_name (TEXT)
  - game_id (TEXT)
  - last_updated (TIMESTAMP)
  - Unique constraint on (market_hash_name, game_id)

- Price History table:
  - item_id (INTEGER)
  - timestamp (TIMESTAMP)
  - price (REAL)
  - volume (INTEGER)
  - Unique constraint on (item_id, timestamp, price, volume)

### Worker Threads
- One worker thread per game
- Each worker processes its assigned game's items
- Implement priority queue for item processing
- Handle worker errors and retries

### Error Handling
- Track failed items per game
- Maximum retry attempts: 3
- Retry delay: 60 seconds
- Log all errors and warnings

## Current Supported Games
1. MapleStory (Game ID: 216150)
2. Counter-Strike 2 (Game ID: 730)

## Data Flow
1. **Collection Phase**
   - Fetch 10 items (1 page) for each game in rotation
   - Continue until each game has 50 items (5 pages)
   - Total batch size: 100 items

2. **Processing Phase**
   - Workers process items from their assigned game's queue
   - Fetch and validate price history
   - Store valid data in database
   - Handle rate limits and errors

3. **Batch Completion**
   - Wait for all items to be processed
   - 5-minute cooldown between batches
   - Start new batch

## Logging
- Log all API requests and responses
- Track rate limit hits and waits
- Monitor queue sizes and failed items
- Record successful and failed operations

## Future Improvements
1. Add support for more games
2. Implement data analysis features
3. Add price trend detection
4. Improve error recovery mechanisms
5. Add configuration file support
6. Implement data export functionality 
