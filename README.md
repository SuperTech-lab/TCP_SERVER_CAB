# LakeShore 370 – Control & Monitoring System (CAB)

<p align="center">
  <img src="logoCAB.png"
       alt="Centro de Astrobiología (CAB - CSIC/INTA)"
       width="500"/>
</p>

## Overview

This application has been developed to control the Lakeshore 370 device, one of the main components in the refrigeration system of the superconducting group. The main reason to develop such system was to enable the group members to control all the Lakeshore functionalities in a remote and easy way. Rather than having to use commands in the terminal, the superconducting group users are now able to change the device's parameters and configurations entirely through the website.

This website (index.html file) has three different tabs for different functionalities:

## Fridge Control

In this tab (selected by default), the information about the temperature of each Lakeshore channel (MXC, STILL, 4K and 50K) is shown, together with all the other functionalities. These functionalities include, among others: P, I and D gain configuration, heater range configuration, curve selection, etc.

## BlackBody Control

This tab is yet to be developed. It was created to manage the Black Body parameters and temperature.

## MXC Comparison

This tab was implemented as a future feature. Here, a comparative chart between a possible future channel's resistance and the MXC temperature is shown. This will be useful, for example, when comparing it with a channel measuring a superconductor, as it will show how the resistance decays alongside the temperature.

Even though there is a considerable amount of code, the main data stream repeats itself in almost every part of the system. The following approach is taken to communicate backend and frontend:

---

# Data Flow (High-Level Overview)

## 1. Device / Simulator

- The source of data is the Lakeshore 370 device. For development and testing without influencing production, the simulator `lakeshore370_dummy.py` has been developed.

## 2. Hardware Abstraction

- The module `lakeshore370.py` implements communication with the hardware (or with the dummy). It provides functions to read temperatures, configure PID gains, heater ranges, curve selection, etc. This is archieved through the PyVisa communication protocol.

## 3. Backend (Servers)

- `tcp_server.py` exposes a TCP interface for clients that want to send commands or receive readings. Here, we initialise the Lakeshore connection, as well as the database one. It also handles all possible commands to send to the Lakeshore device.
- `http_server.py` serves the web UI and any HTTP endpoints used by the UI. It gets the data from the TCP server and delivers it to the `index.html` afterwards. Moreover, it also has an endpoint to retrieve the data from previous RUNS.

## 4. Frontend

- The user interface is in `index.html` with logic in `index.js`. The frontend obtains data from the `http_server.py` JSON via the /get-data endpoint. Afterwards, it parses all the JSON components to the variables, being able to show how they change in live. The configuration of all parameters is also developed in a way that everytime the user confirms the changes made, `index.html` sends the commands to the TCP server, who then applies it to the Lakeshore device.

## 5. Runtime Flow (Overview)

### Device Readout and Broadcasting (TCP Server)

- The driver in `lakeshore370.py` is used by `tcp_server.py`'s `lakeshore_temperature_sensor()` loop to read temperatures, resistances and power, together with control and sensor parameters.
- `tcp_server.py` composes a single text message per sample containing many `key:value` pairs (for example, `50K: 0.05,4K: 0.3,STILL: OFF,MXC: 0.01,MXCSP:...`).
- The TCP server accepts two client modes: subscriber mode and command mode. Subscribers connect, send `SUB\n` and remain connected to receive the continuous broadcasts; command-mode connections send a single command and receive a one-line reply.

### HTTP Server as a TCP Subscriber

- `http_server.py` connects to the TCP server as a subscriber (it opens a persistent TCP socket, sends `SUB\n` and runs `receive_sensor_data()` in a background thread).
- `receive_sensor_data()` reads the content from the TCP socket, parses the `key:value` pairs and updates the global variables that represent the latest snapshot for each channel and parameter.
- `http_server.py` exposes an endpoint `/get-data` that returns the current snapshot as a JSON from those global variables. This is how the frontend obtains the latest values.

### Frontend Interactions

- Reading data: the frontend requests `/get-data` (periodically) to obtain a snapshot JSON used to update the UI widgets and charts.
- Commands/configuration: when the user changes a parameter, the frontend POSTs to `/send-command`. The HTTP server opens a TCP connection, sends the command text, reads the single-line response and returns it to the frontend.

---

# Relevant Files

- `lakeshore370.py`: device driver and low-level API.
- `lakeshore370_dummy.py`: simulator for development and tests.
- `tcp_server.py`: TCP server managing client connections and commands.
- `http_server.py`: HTTP server for the UI and related endpoints.
- `index.html`, `index.js`: web interface and client-side logic.
- `default_config.py`: default values and configuration.
- `dbconfig.sql`: postgresql configuration file for the database.
