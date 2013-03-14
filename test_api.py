import api
import os
import unittest
from mock import patch
from collections import namedtuple


class DatabaseTest(object):

    @classmethod
    def setUpClass(cls):
        os.environ["DB_PATH"] = ":memory:"
        reload(api)
        sql_path = os.path.realpath(os.path.join(__file__, "../database.sql"))
        f = open(sql_path)
        sql = f.read().replace("\n", "")
        c = api.conn.cursor()
        c.execute(sql)

    @classmethod
    def tearDownClass(cls):
        c = api.conn.cursor()
        c.execute("drop table instance_app;")
        api.conn.close()


class TestHelper(object):

    def fake_reservation(self):
        Reservation = namedtuple("Reservation", ["instances"])
        Instance = namedtuple("Instance", ["id", "private_ip_address"])
        return Reservation(instances=[Instance(id="i-1", private_ip_address="192.169.56.101")])


class CreateInstanceTestCase(DatabaseTest, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.api = api.api.test_client()
        cls.helper = TestHelper()
        os.environ["ACCESS_KEY"] = "access"
        os.environ["SECRET_KEY"] = "secret"
        os.environ["AMI_ID"] = "ami-123"
        os.environ["SUBNET_ID"] = "subnet-123"
        reload(api)
        DatabaseTest.setUpClass()

    def tearDown(self):
        c = api.conn.cursor()
        c.execute("delete from instance_app;")

    @classmethod
    def tearDownClass(cls):
        del os.environ["ACCESS_KEY"]
        del os.environ["SECRET_KEY"]
        del os.environ["AMI_ID"]
        del os.environ["SUBNET_ID"]
        DatabaseTest.tearDownClass()

    @patch("boto.ec2.connection.EC2Connection")
    def test_create_instance_should_return_201(self, mock):
        resp = self.api.post("/resources", data={"name": "someapp"})
        self.assertEqual(resp.status_code, 201)

    @patch("boto.ec2.connection.EC2Connection")
    def test_should_connect_with_ec2_using_environment_variables(self, mock):
        self.api.post("/resources", data={"name": "someapp"})
        mock.assert_called_once_with(api.access_key, api.secret_key)

    @patch("boto.ec2.connection.EC2Connection")
    def test_should_create_instance_on_ec2(self, mock):
        instance = mock.return_value
        r = self.helper.fake_reservation()
        instance.run_instances.return_value = [r]
        self.api.post("/resources", data={"name": "someapp"})
        self.assertTrue(instance.run_instances.called)

    @patch("boto.ec2.connection.EC2Connection")
    def test_should_create_instance_on_ec2_using_subnet_and_ami_defined_in_env_var(self, mock):
        instance = mock.return_value
        self.api.post("/resources", data={"name": "someapp"})
        instance.run_instances.assert_called_once_with(image_id=api.ami_id, subnet_id=api.subnet_id)

    @patch("boto.ec2.connection.EC2Connection")
    def test_should_store_instance_id_and_app_name_on_database(self, mock):
        instance = mock.return_value
        r = self.helper.fake_reservation()
        instance.run_instances.return_value = [r]
        self.api.post("/resources", data={"name": "someapp"})
        c = api.conn.cursor()
        c.execute("select * from instance_app;")
        result = c.fetchall()
        expected = [("i-1", "someapp")]
        self.assertListEqual(expected, result)


class DeleteInstanceTestCase(DatabaseTest, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.api = api.api.test_client()
        os.environ["ACCESS_KEY"] = "access"
        os.environ["SECRET_KEY"] = "secret"
        reload(api)
        DatabaseTest.setUpClass()

    @classmethod
    def tearDownClass(cls):
        del os.environ["ACCESS_KEY"]
        del os.environ["SECRET_KEY"]
        DatabaseTest.tearDownClass()

    def tearDown(self):
        c = api.conn.cursor()
        c.execute("delete from instance_app;")

    @patch("boto.ec2.connection.EC2Connection")
    @patch("api._get_instance_id")
    def test_should_get_and_be_success(self, mock, ec2_mock):
        mock.return_value = ["i-1"]
        r = self.api.delete("/resources/service_instance_name")
        self.assertEqual(200, r.status_code)

    @patch("boto.ec2.connection.EC2Connection")
    def test_should_call_ec2_terminate_instances(self, mock):
        instance = mock.return_value
        instance.terminate_instances.return_value = ["i-1"]
        c = api.conn.cursor()
        c.execute("insert into instance_app values ('i-1', 'si_name')")
        self.api.delete("/resources/si_name")
        instance.terminate_instances.assert_called_once_with(instance_ids=["i-1"])

    @patch("boto.ec2.connection.EC2Connection")
    def test_should_remove_record_from_the_database(self, mock):
        c = api.conn.cursor()
        c.execute("insert into instance_app values ('i-1', 'si_name')")
        self.api.delete("/resources/si_name")
        c.execute("select * from instance_app where app_name='si_name'")
        results = c.fetchall()
        self.assertListEqual([], results)


class BindTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.api = api.api.test_client()
        cls.helper = TestHelper()
        os.environ["ACCESS_KEY"] = "access"
        os.environ["SECRET_KEY"] = "secret"
        reload(api)

    @classmethod
    def tearDownClass(cls):
        del os.environ["ACCESS_KEY"]
        del os.environ["SECRET_KEY"]

    @patch("subprocess.call")
    @patch("boto.ec2.connection.EC2Connection")
    @patch("api._get_instance_id")
    def test_should_get_instance_id_from_database(self, mock, ec2_mock, sp_mock):
        sp_mock.return_value = 0
        mock.return_value = "i-1"
        resp = self.api.post("/resources/si_name")
        self.assertEqual(201, resp.status_code)
        mock.assert_called_once_with(service_instance="si_name")

    @patch("subprocess.call")
    @patch("boto.ec2.connection.EC2Connection")
    @patch("api._get_instance_id")
    def test_should_get_instance_ip_from_amazon(self, mock, ec2_mock, sp_mock):
        sp_mock.return_value = 0
        mock.return_value = "i-1"
        instance = ec2_mock.return_value
        instance.get_all_instances.return_value = [self.helper.fake_reservation()]
        self.api.post("/resources/si_name")
        instance.get_all_instances.assert_called_once_with(instance_ids=["i-1"])

    @patch("subprocess.call")
    @patch("boto.ec2.connection.EC2Connection")
    @patch("api._get_instance_ip")
    @patch("api._get_instance_id")
    def test_should_ssh_into_service_instance_and_update_vcl_file_using_template(self, mock, ip_mock, ec2_mock, sp_mock):
        si_ip =  "10.2.2.1"
        app_ip = "10.1.1.2"
        sp_mock.return_value = 0
        ip_mock.return_value = si_ip
        self.api.post("/resources/si_name", data={"hostname": app_ip})
        self.assertTrue(sp_mock.called)
        cmd = "sudo bash -c 'echo \"{0}\" > /etc/varnish/default.vcl'".format(api.vcl_template.format(app_ip))
        expected = ["ssh", si_ip, "-l", "ubuntu", cmd]
        cmd_arg = sp_mock.call_args_list[0][0][0]
        self.assertEqual(expected, cmd_arg)


class UnbindTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.api = api.api.test_client()
        cls.helper = TestHelper()
        os.environ["ACCESS_KEY"] = "access"
        os.environ["SECRET_KEY"] = "secret"
        reload(api)

    @classmethod
    def tearDownClass(cls):
        del os.environ["ACCESS_KEY"]
        del os.environ["SECRET_KEY"]

    @patch("boto.ec2.connection.EC2Connection")
    @patch("api._get_instance_id")
    def test_unbind_should_get_instance_id(self, mock, ec2_mock):
        mock.return_value = "i-1"
        resp = self.api.delete("/resources/si_name/host/10.1.1.2")
        self.assertEqual(200, resp.status_code)
        mock.assert_called_once_with(service_instance="si_name")


class HelpersTestcase(unittest.TestCase):

    def test_get_database_name_should_return_absolute_path_to_it(self):
        del os.environ["DB_PATH"]
        db_name = api._get_database_name()
        expected = os.path.realpath(os.path.join(__file__, "../", api.default_db_name))
        self.assertEqual(expected, db_name)

    def test_get_database_name_should_use_DB_PATH_env_var_when_its_set(self):
        os.environ["DB_PATH"] = ":memory:"
        reload(api)
        got = api._get_database_name()
        self.assertEqual(os.environ["DB_PATH"], got)
        del os.environ["DB_PATH"]



if __name__ == "__main__":
    unittest.main()
