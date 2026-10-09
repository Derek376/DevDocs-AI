# AtlasDocs HTTP client

The AtlasDocs HTTP client read timeout is 30 seconds.
The HTTP client retries failed requests at most 2 times, with a 500 millisecond delay between retries.
These HTTP settings do not define database transaction retries.
