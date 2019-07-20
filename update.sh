#!/usr/bin/env bash
sudo service apache2 stop

sudo mkdir ../tmp

sudo cp -r ./cavoke_server/secret ../tmp

cd ..
sudo rm -rf cavoke_server
cd tmp

sudo git clone https://github.com/cavoke-project/cavoke-server.git
sudo mv secret ./cavoke-server/cavoke_server

sudo mkdir ../cavoke_server
sudo mv cavoke-server/* ../cavoke_server

cd ..
sudo rm -rf tmp
cd cavoke_server

sudo chmod 777 .
virtualenv venv
source ./venv/bin/activate
pip install -r ./requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic
deactivate

sudo rm /etc/apache2/sites-available/000-default.conf
sudo mv config/default.conf /etc/apache2/sites-available/000-default.conf

sudo service apache2 start
echo "Done!"
