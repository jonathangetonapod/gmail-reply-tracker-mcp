#!/usr/bin/env node
/**
 * HTTP MCP Client - Proxies stdio MCP protocol to HTTP endpoint
 *
 * Usage: node http-mcp-client.js <server-url> <bearer-token>
 */

const https = require('https');
const http = require('http');
const readline = require('readline');

// Get arguments
const SERVER_URL = process.argv[2];
const BEARER_TOKEN = process.argv[3];

if (!SERVER_URL || !BEARER_TOKEN) {
  console.error('Usage: node http-mcp-client.js <server-url> <bearer-token>');
  process.exit(1);
}

// Parse URL
const url = new URL(SERVER_URL);
const client = url.protocol === 'https:' ? https : http;

// Setup readline for stdin
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
});

// Handle incoming messages from Claude Desktop
rl.on('line', async (line) => {
  let requestId = 1;  // Default ID
  try {
    const request = JSON.parse(line);
    requestId = request.id !== undefined && request.id !== null ? request.id : 1;

    // Send to HTTP server
    const response = await sendRequest(request);

    // Send response back to Claude Desktop
    console.log(JSON.stringify(response));
  } catch (error) {
    console.error('Error processing message:', error.message);
    // Send error response with proper ID
    const errorResponse = {
      jsonrpc: '2.0',
      id: requestId,
      error: {
        code: -32603,
        message: error.message
      }
    };
    console.log(JSON.stringify(errorResponse));
  }
});

// Function to send HTTP request
function sendRequest(data) {
  return new Promise((resolve, reject) => {
    const postData = JSON.stringify(data);

    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
        'Authorization': `Bearer ${BEARER_TOKEN}`
      }
    };

    const req = client.request(options, (res) => {
      let body = '';

      res.on('data', (chunk) => {
        body += chunk;
      });

      res.on('end', () => {
        try {
          const response = JSON.parse(body);
          resolve(response);
        } catch (error) {
          reject(new Error(`Invalid JSON response: ${body}`));
        }
      });
    });

    req.on('error', (error) => {
      reject(error);
    });

    req.write(postData);
    req.end();
  });
}

// Handle errors
process.on('uncaughtException', (error) => {
  console.error('Uncaught exception:', error);
  process.exit(1);
});

process.on('SIGINT', () => {
  process.exit(0);
});

process.on('SIGTERM', () => {
  process.exit(0);
});
