-- ============================================================
-- SaaS POS — Database Migration Script (MySQL 8.0 compatible)
-- ============================================================

-- ─────────────────────────────────────────────────────────
-- 1. Create branches table (NEW)
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `branches` (
    `id`         INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  INT NOT NULL,
    `name`       VARCHAR(100) NOT NULL,
    `address`    VARCHAR(200),
    `city`       VARCHAR(50),
    `phone`      VARCHAR(20),
    `manager_id` INT,
    `is_active`  TINYINT(1) DEFAULT 1,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_branch_tenant` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────
-- 2. Create inventory_movements table (NEW)
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `inventory_movements` (
    `id`               INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`        INT,
    `branch_id`        INT,
    `product_id`       INT NOT NULL,
    `movement_type`    VARCHAR(20) NOT NULL,
    `quantity`         FLOAT NOT NULL,
    `reference_type`   VARCHAR(20),
    `reference_id`     INT,
    `idempotency_key`  VARCHAR(100),
    `notes`            VARCHAR(200),
    `user`             VARCHAR(100),
    `created_at`       DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_invmov_product` (`product_id`),
    INDEX `idx_invmov_tenant`  (`tenant_id`),
    INDEX `idx_invmov_date`    (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────
-- 3. Add columns to products (safe, one at a time)
-- ─────────────────────────────────────────────────────────
SET @dbname = DATABASE();

-- products.tenant_id
SET @col = 'tenant_id'; SET @tbl = 'products';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- products.branch_id
SET @col = 'branch_id'; SET @tbl = 'products';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- products.updated_at
SET @col = 'updated_at'; SET @tbl = 'products';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────
-- 4. categories.tenant_id
-- ─────────────────────────────────────────────────────────
SET @col = 'tenant_id'; SET @tbl = 'categories';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────
-- 5. customers.tenant_id
-- ─────────────────────────────────────────────────────────
SET @col = 'tenant_id'; SET @tbl = 'customers';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────
-- 6. users columns
-- ─────────────────────────────────────────────────────────
SET @col = 'tenant_id'; SET @tbl = 'users';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'branch_id'; SET @tbl = 'users';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'last_login'; SET @tbl = 'users';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` DATETIME NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'is_active'; SET @tbl = 'users';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` TINYINT(1) DEFAULT 1'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────
-- 7. sales columns
-- ─────────────────────────────────────────────────────────
SET @col = 'idempotency_key'; SET @tbl = 'sales';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` VARCHAR(100) NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'tenant_id'; SET @tbl = 'sales';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'branch_id'; SET @tbl = 'sales';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` INT NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'discount_amount'; SET @tbl = 'sales';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` FLOAT DEFAULT 0'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'vat_amount'; SET @tbl = 'sales';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` FLOAT DEFAULT 0'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────
-- 8. tenants columns
-- ─────────────────────────────────────────────────────────
SET @col = 'slug'; SET @tbl = 'tenants';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` VARCHAR(50) NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col = 'updated_at'; SET @tbl = 'tenants';
SET @sql = IF(
    NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@dbname AND TABLE_NAME=@tbl AND COLUMN_NAME=@col),
    CONCAT('ALTER TABLE `', @tbl, '` ADD COLUMN `', @col, '` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────
-- 9. Seed data — insert tenant + branch + link users
-- ─────────────────────────────────────────────────────────
INSERT IGNORE INTO `tenants` (id, name, slug, plan, is_active)
VALUES (1, 'Main Store', 'mainstore', 'pro', 1);

INSERT IGNORE INTO `branches` (id, tenant_id, name, city, is_active)
VALUES (1, 1, 'Main Branch', 'Cairo', 1);

-- Link all existing users to tenant 1 / branch 1
UPDATE `users` SET tenant_id = 1, branch_id = 1 WHERE tenant_id IS NULL;

-- ─────────────────────────────────────────────────────────
-- Done!
-- ─────────────────────────────────────────────────────────
SELECT 'Migration complete ✅' AS status;
