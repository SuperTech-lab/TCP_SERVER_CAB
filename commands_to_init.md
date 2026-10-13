ps aux | grep python // check processes
kill ID // kill process by ID
nohup python3 -u http_server.py > ~/http_server_step_ramp_test1.log 2>&1 & // http_server.py or tcp_server.py
tail -f ~/http_server_step_ramp_test1.log // read log in real time

http://192.168.38.3:8080 // URL web visualizer