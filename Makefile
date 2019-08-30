img:
	docker -H 10.0.1.140 build  -t r.c.videogorillas.com/craft:master .
	docker -H 10.0.1.140 push r.c.videogorillas.com/craft:master

