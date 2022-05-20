# e-queo-pdf
create pdf notes for e-queo course

# Setup
create `config.ini` next to the script file with the following content
```
[e-queo]
module_id= your module id 
auth_token= token
```
for `auth_token` use token for e-queo.online (from Authorization header)<br>
**note:** token lives 3600 s from being refreshed<br>
for `module_id` use module id for your course from the address bar 
![](https://i.imgur.com/jvbTPlW.png) 
