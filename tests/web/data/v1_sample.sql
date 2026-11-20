PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE project (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO project VALUES(1,'вул. Шевченка','навчальний проєкт','2026-11-19 23:10:29');
CREATE TABLE application (
	id INTEGER NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	comment TEXT, 
	status VARCHAR(20) NOT NULL, 
	project_id INTEGER, 
	mode VARCHAR(10), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	queued_at DATETIME, 
	started_at DATETIME, 
	finished_at DATETIME, 
	progress FLOAT NOT NULL, 
	progress_text VARCHAR(200) NOT NULL, 
	error TEXT, 
	result_dir VARCHAR(400), 
	duplicate_of_id INTEGER, 
	merged BOOLEAN NOT NULL, 
	decision_comment TEXT, 
	decided_at DATETIME, 
	has_assessment BOOLEAN, 
	damage_category VARCHAR(4), 
	condition_category INTEGER, 
	escalation VARCHAR(20), 
	confidence FLOAT, 
	cost_low INTEGER, 
	cost_high INTEGER, 
	cost_total INTEGER, 
	simulated BOOLEAN NOT NULL, 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES project (id), 
	FOREIGN KEY(duplicate_of_id) REFERENCES application (id)
);
INSERT INTO application VALUES(1,'вул. Шевченка, 12',NULL,'Approved',1,'video','2026-11-19 23:10:29','2026-11-19 23:10:29','2026-11-20 01:10:29.159243','2026-11-20 01:10:29.270396','2026-11-20 01:10:29.311468',1.0,'Готово (симуляція)',NULL,'DATA/results/1',NULL,0,'затверджено оператором','2026-11-20 01:10:29.425016',1,'III',4,'confirmed',0.75,2158948,3306743,2732846,1,1);
INSERT INTO application VALUES(2,'Школа №5',NULL,'Approved',NULL,'photo','2026-11-19 23:10:29','2026-11-19 23:10:29','2026-11-20 01:10:29.170635','2026-11-20 01:10:29.313614','2026-11-20 01:10:29.322167',1.0,'Готово (симуляція)',NULL,'DATA/results/2',NULL,0,'затверджено оператором','2026-11-20 01:10:29.472438',1,'I',2,'preliminary',0.5999999999999999778,11266,29700,20483,1,1);
INSERT INTO application VALUES(3,'вул. Шевченка, 14',NULL,'Processed',1,'photos','2026-11-19 23:10:29','2026-11-20 01:10:29.358232','2026-11-20 01:10:29.186534','2026-11-20 01:10:29.323838','2026-11-20 01:10:29.358239',1.0,'Готово (симуляція)',NULL,'DATA/results/3',NULL,0,NULL,NULL,1,'II',4,'preliminary',0.5999999999999999778,1861691,2851450,2356570,1,1);
INSERT INTO application VALUES(4,'Тест збою',NULL,'Failed',NULL,'photo','2026-11-19 23:10:29','2026-11-20 01:10:29.366771','2026-11-20 01:10:29.199881','2026-11-20 01:10:29.360103','2026-11-20 01:10:29.366778',0.05000000000000000277,'Симуляція: підготовка','SimulatedFailure: simulated processing failure',NULL,NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,1);
INSERT INTO application VALUES(5,'Мало фото',NULL,'Declined',NULL,'video','2026-11-19 23:10:29','2026-11-19 23:10:29','2026-11-20 01:10:29.208440','2026-11-20 01:10:29.369092','2026-11-20 01:10:29.386463',1.0,'Готово (симуляція)',NULL,'DATA/results/5',NULL,0,'потрібні фото з інших сторін','2026-11-20 01:10:29.480533',0,NULL,NULL,'insufficient_data',0.2999999999999999889,NULL,NULL,NULL,1,1);
INSERT INTO application VALUES(6,'пр. Свободи, 3',NULL,'Processed',NULL,'video','2026-11-19 23:10:29','2026-11-20 01:10:29.421318','2026-11-20 01:10:29.259419','2026-11-20 01:10:29.388494','2026-11-20 01:10:29.421325',1.0,'Готово (симуляція)',NULL,'DATA/results/6',NULL,0,NULL,NULL,1,'I',2,'preliminary',0.5999999999999999778,771917,1182303,977110,1,1);
INSERT INTO application VALUES(7,'Школа №5 (повторно)',NULL,'Created',NULL,'photo','2026-11-19 23:10:29','2026-11-19 23:10:29',NULL,NULL,NULL,0.0,'Можливий дублікат заявки №2',NULL,NULL,2,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,1);
CREATE TABLE application_file (
	id INTEGER NOT NULL, 
	application_id INTEGER NOT NULL, 
	name VARCHAR(300) NOT NULL, 
	path VARCHAR(400) NOT NULL, 
	bytes INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(application_id) REFERENCES application (id)
);
INSERT INTO application_file VALUES(1,1,'download11_3_full.mp4','DATA/uploads/1/download11_3_full.mp4',9748696,'477b0d1f1dc3b204f47fc9dbb4e53585d04688dce92add09bdeaee00cd39630f');
INSERT INTO application_file VALUES(2,2,'photo_2024-05-04_17-13-39.jpg','DATA/uploads/2/photo_2024-05-04_17-13-39.jpg',88751,'c3d0de2ba742104f26c59f4a5e017c32a063b7a9de597032664d9987fca5a435');
INSERT INTO application_file VALUES(3,3,'download12_2_0004.jpg','DATA/uploads/3/download12_2_0004.jpg',113329,'f29ed984c13b1d2fe2d96720c9e952959cd5ba2ea6de2ce0f6e13a6619cdba6d');
INSERT INTO application_file VALUES(4,3,'download12_2_0012.jpg','DATA/uploads/3/download12_2_0012.jpg',78212,'f4138bcbce80ae1002af042b1ccc9e6497120f9c8b57f4c88ddf0cfe63798858');
INSERT INTO application_file VALUES(5,3,'download12_2_0022.jpg','DATA/uploads/3/download12_2_0022.jpg',87840,'591f5fc3cd43c227fb9d0712998763f2506b13150b6f652910a40504ce032cd1');
INSERT INTO application_file VALUES(6,3,'download12_2_0030.jpg','DATA/uploads/3/download12_2_0030.jpg',102050,'5715ec43a3eb2e21a4eca35ef5c6c9e50560275cd7d8b258e6613e201436054f');
INSERT INTO application_file VALUES(7,3,'download12_2_0038.jpg','DATA/uploads/3/download12_2_0038.jpg',128258,'a5566d95b6ad5c2a9a8aa4099d29f838eee1ed35b7d294bccfff748493bc8bf4');
INSERT INTO application_file VALUES(8,4,'fail_test.jpg','DATA/uploads/4/fail_test.jpg',747144,'abce513eb99ea12d4feab2eae00ca4444c9e9bea35493eb0fa8ef3fdcb74c88c');
INSERT INTO application_file VALUES(9,5,'lowconf_test.jpg','DATA/uploads/5/lowconf_test.jpg',612253,'f75925ff8c65703747aa7ae7d584fca0375d673550585180bc416430e733dc40');
INSERT INTO application_file VALUES(10,6,'download10_full.mp4','DATA/uploads/6/download10_full.mp4',7399965,'b8d81c50e4b1226ab7aacca1a58630fa3123a2eda38c0be698e802e7c8b1cac2');
INSERT INTO application_file VALUES(11,7,'copy_of_photo_single.jpg','DATA/uploads/7/copy_of_photo_single.jpg',88751,'c3d0de2ba742104f26c59f4a5e017c32a063b7a9de597032664d9987fca5a435');
CREATE TABLE status_change (
	id INTEGER NOT NULL, 
	application_id INTEGER NOT NULL, 
	from_status VARCHAR(20), 
	to_status VARCHAR(20) NOT NULL, 
	at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	comment TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(application_id) REFERENCES application (id)
);
INSERT INTO status_change VALUES(1,1,NULL,'Created','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(2,2,NULL,'Created','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(3,3,NULL,'Created','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(4,4,NULL,'Created','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(5,5,NULL,'Created','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(6,6,NULL,'Created','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(7,1,'Created','Processing','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(8,1,'Processing','Processed','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(9,2,'Created','Processing','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(10,2,'Processing','Processed','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(11,3,'Created','Processing','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(12,3,'Processing','Processed','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(13,4,'Created','Processing','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(14,4,'Processing','Failed','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(15,5,'Created','Processing','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(16,5,'Processing','Processed','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(17,6,'Created','Processing','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(18,6,'Processing','Processed','2026-11-19 23:10:29',NULL);
INSERT INTO status_change VALUES(19,1,'Processed','Approved','2026-11-19 23:10:29','затверджено оператором');
INSERT INTO status_change VALUES(20,2,'Processed','Approved','2026-11-19 23:10:29','затверджено оператором');
INSERT INTO status_change VALUES(21,5,'Processed','Declined','2026-11-19 23:10:29','потрібні фото з інших сторін');
INSERT INTO status_change VALUES(22,7,NULL,'Created','2026-11-19 23:10:29',NULL);
CREATE INDEX ix_application_project_id ON application (project_id);
CREATE INDEX ix_application_simulated ON application (simulated);
CREATE INDEX ix_application_status ON application (status);
CREATE INDEX ix_application_escalation ON application (escalation);
CREATE INDEX ix_application_condition_category ON application (condition_category);
CREATE INDEX ix_application_damage_category ON application (damage_category);
CREATE INDEX ix_application_file_sha256 ON application_file (sha256);
CREATE INDEX ix_application_file_application_id ON application_file (application_id);
CREATE INDEX ix_status_change_application_id ON status_change (application_id);
COMMIT;
