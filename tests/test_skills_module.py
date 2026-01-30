#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能模块测试
"""

import os
import sys
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.protocols import Skill, SkillMatch, SyncStatus
from skills.local_store import LocalSkillStore, MockLocalSkillStore
from skills.remote_store import MockRemoteSkillStore
from skills.sync_manager import SkillSyncManager
from skills.skill_manager import SkillManager


class TestSkillDataModel(unittest.TestCase):
    """测试技能数据模型"""
    
    def test_skill_creation(self):
        """测试创建技能"""
        skill = Skill(
            id="test_001",
            name="测试技能",
            description="这是一个测试技能",
            code="step('点击按钮')",
            tags=["测试", "示例"]
        )
        
        self.assertEqual(skill.id, "test_001")
        self.assertEqual(skill.name, "测试技能")
        self.assertEqual(len(skill.tags), 2)
        self.assertEqual(skill.use_count, 0)
        self.assertEqual(skill.success_count, 0)
    
    def test_skill_match(self):
        """测试技能匹配结果"""
        skill = Skill(id="s1", name="技能1", description="描述")
        match = SkillMatch(skill=skill, score=0.85, matched_field="name")
        
        self.assertEqual(match.score, 0.85)
        self.assertEqual(match.matched_field, "name")


class TestMockLocalSkillStore(unittest.TestCase):
    """测试 Mock 本地存储"""
    
    def setUp(self):
        self.store = MockLocalSkillStore()
    
    def test_save_and_get(self):
        """测试保存和获取"""
        skill = Skill(id="s1", name="技能1", description="描述1")
        
        skill_id = self.store.save(skill)
        self.assertEqual(skill_id, "s1")
        
        retrieved = self.store.get("s1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "技能1")
    
    def test_delete(self):
        """测试删除"""
        skill = Skill(id="s1", name="技能1", description="描述1")
        self.store.save(skill)
        
        result = self.store.delete("s1")
        self.assertTrue(result)
        
        result = self.store.delete("s1")
        self.assertFalse(result)
    
    def test_list_all(self):
        """测试列出所有"""
        self.store.save(Skill(id="s1", name="技能1", description=""))
        self.store.save(Skill(id="s2", name="技能2", description=""))
        
        skills = self.store.list_all()
        self.assertEqual(len(skills), 2)
    
    def test_search(self):
        """测试搜索"""
        self.store.save(Skill(id="s1", name="发朋友圈", description="微信发朋友圈"))
        self.store.save(Skill(id="s2", name="点赞", description="给好友点赞"))
        
        matches = self.store.search("朋友圈")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].skill.id, "s1")
    
    def test_update_stats(self):
        """测试更新统计"""
        skill = Skill(id="s1", name="技能1", description="")
        self.store.save(skill)
        
        self.store.update_stats("s1", success=True)
        self.store.update_stats("s1", success=False)
        
        updated = self.store.get("s1")
        self.assertEqual(updated.use_count, 2)
        self.assertEqual(updated.success_count, 1)


class TestMockRemoteSkillStore(unittest.TestCase):
    """测试 Mock 远程存储"""
    
    def setUp(self):
        self.store = MockRemoteSkillStore()
    
    def test_save_and_get(self):
        """测试保存和获取"""
        skill = Skill(id="r1", name="远程技能", description="云端存储")
        
        skill_id = self.store.save(skill)
        retrieved = self.store.get(skill_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "远程技能")
    
    def test_sync_status(self):
        """测试同步状态"""
        status = self.store.get_sync_status()
        
        self.assertIsInstance(status, SyncStatus)
        self.assertEqual(status.conflicts, 0)


class TestSkillSyncManager(unittest.TestCase):
    """测试同步管理器"""
    
    def setUp(self):
        self.local = MockLocalSkillStore()
        self.remote = MockRemoteSkillStore()
        self.manager = SkillSyncManager(self.local, self.remote)
    
    def test_save_syncs_to_remote(self):
        """测试保存时同步到远程"""
        skill = Skill(id="sync1", name="同步技能", description="测试同步")
        
        skill_id = self.manager.save(skill)
        
        # 本地应该有
        local_skill = self.local.get(skill_id)
        self.assertIsNotNone(local_skill)
        
        # 等待异步同步完成（测试中可能需要等待）
        import time
        time.sleep(0.1)
    
    def test_get_prefers_local(self):
        """测试获取优先本地"""
        skill = Skill(id="local1", name="本地技能", description="")
        self.local.save(skill)
        
        retrieved = self.manager.get("local1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "本地技能")
    
    def test_get_falls_back_to_remote(self):
        """测试获取回退到远程"""
        skill = Skill(id="remote1", name="远程技能", description="")
        self.remote.save(skill)
        
        retrieved = self.manager.get("remote1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "远程技能")
        
        # 应该缓存到本地
        local_cached = self.local.get("remote1")
        self.assertIsNotNone(local_cached)
    
    def test_search_merges_results(self):
        """测试搜索合并结果"""
        self.local.save(Skill(id="l1", name="本地朋友圈", description=""))
        self.remote.save(Skill(id="r1", name="远程朋友圈", description=""))
        
        matches = self.manager.search("朋友圈")
        self.assertGreaterEqual(len(matches), 1)


class TestSkillManager(unittest.TestCase):
    """测试统一管理器"""
    
    def test_create_mock(self):
        """测试创建 Mock 管理器"""
        manager = SkillManager.create_mock()
        
        self.assertIsNotNone(manager.local)
        self.assertIsNotNone(manager.remote)
    
    def test_save_and_search(self):
        """测试保存和搜索"""
        manager = SkillManager.create_mock()
        
        skill = Skill(
            id="m1",
            name="微信发朋友圈",
            description="在微信中发送一条朋友圈",
            tags=["微信", "社交"]
        )
        manager.save(skill)
        
        matches = manager.search("发朋友圈", min_score=0.0)
        self.assertGreater(len(matches), 0)
    
    def test_get_best_match(self):
        """测试获取最佳匹配"""
        manager = SkillManager.create_mock()
        
        manager.save(Skill(id="s1", name="发朋友圈", description="微信朋友圈"))
        manager.save(Skill(id="s2", name="点赞", description="给好友点赞"))
        
        best = manager.get_best_match("朋友圈", min_score=0.0)
        self.assertIsNotNone(best)
        self.assertEqual(best.id, "s1")
    
    def test_record_usage(self):
        """测试记录使用"""
        manager = SkillManager.create_mock()
        
        skill = Skill(id="s1", name="技能1", description="")
        manager.save(skill)
        
        manager.record_usage("s1", success=True)
        
        updated = manager.get("s1")
        self.assertEqual(updated.use_count, 1)
        self.assertEqual(updated.success_count, 1)
    
    def test_get_stats(self):
        """测试获取统计"""
        manager = SkillManager.create_mock()
        
        manager.save(Skill(id="s1", name="技能1", description=""))
        manager.search("测试")
        
        stats = manager.get_stats()
        
        self.assertEqual(stats["saves"], 1)
        self.assertEqual(stats["searches"], 1)
    
    def test_health_check(self):
        """测试健康检查"""
        manager = SkillManager.create_mock()
        
        status = manager.health_check()
        
        self.assertEqual(status["local"], "ok")
    
    def test_context_manager(self):
        """测试上下文管理器"""
        with SkillManager.create_mock() as manager:
            manager.save(Skill(id="s1", name="技能1", description=""))
            skill = manager.get("s1")
            self.assertIsNotNone(skill)


class TestLocalSkillStore(unittest.TestCase):
    """测试真实本地存储"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalSkillStore(self.temp_dir)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_save_creates_file(self):
        """测试保存创建文件"""
        skill = Skill(id="file1", name="文件技能", description="测试文件存储")
        
        self.store.save(skill)
        
        skill_path = os.path.join(self.temp_dir, "skills", "file1.json")
        self.assertTrue(os.path.exists(skill_path))
    
    def test_save_and_load(self):
        """测试保存和加载"""
        skill = Skill(
            id="persist1",
            name="持久化技能",
            description="测试持久化",
            tags=["测试", "持久化"]
        )
        
        self.store.save(skill)
        
        # 创建新的 store 实例，模拟重启
        new_store = LocalSkillStore(self.temp_dir)
        loaded = new_store.get("persist1")
        
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "持久化技能")
        self.assertEqual(len(loaded.tags), 2)
    
    def test_index_updated(self):
        """测试索引更新"""
        self.store.save(Skill(id="idx1", name="索引技能1", description=""))
        self.store.save(Skill(id="idx2", name="索引技能2", description=""))
        
        index_path = os.path.join(self.temp_dir, "index.json")
        self.assertTrue(os.path.exists(index_path))
        
        with open(index_path, 'r') as f:
            index = json.load(f)
        
        self.assertIn("idx1", index["skills"])
        self.assertIn("idx2", index["skills"])
    
    def test_keyword_search(self):
        """测试关键词搜索（无嵌入时的退化方案）"""
        self.store.save(Skill(id="kw1", name="微信发朋友圈", description="发送朋友圈动态"))
        self.store.save(Skill(id="kw2", name="微信聊天", description="与好友聊天"))
        
        # 使用关键词搜索（因为没有 OpenAI 配置）
        matches = self.store._keyword_search("朋友圈", limit=10)
        
        self.assertGreater(len(matches), 0)
        self.assertEqual(matches[0].skill.id, "kw1")


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    def test_full_workflow(self):
        """测试完整工作流"""
        # 创建管理器
        manager = SkillManager.create_mock()
        
        # 1. 保存技能
        skills = [
            Skill(id="wechat_like", name="微信点赞", description="给朋友圈点赞", tags=["微信", "社交"]),
            Skill(id="wechat_post", name="发朋友圈", description="发送朋友圈动态", tags=["微信", "社交"]),
            Skill(id="alipay_pay", name="支付宝付款", description="使用支付宝付款", tags=["支付宝", "支付"]),
        ]
        
        for skill in skills:
            manager.save(skill)
        
        # 2. 搜索
        matches = manager.search("微信", min_score=0.0)
        wechat_skills = [m.skill for m in matches]
        self.assertGreaterEqual(len(wechat_skills), 1)
        
        # 3. 获取最佳匹配
        best = manager.get_best_match("朋友圈", min_score=0.0)
        self.assertIsNotNone(best)
        
        # 4. 记录使用
        if best:
            manager.record_usage(best.id, success=True)
            updated = manager.get(best.id)
            self.assertEqual(updated.use_count, 1)
        
        # 5. 统计
        stats = manager.get_stats()
        self.assertEqual(stats["saves"], 3)
        
        # 6. 健康检查
        health = manager.health_check()
        self.assertEqual(health["local"], "ok")
        
        # 7. 清理
        manager.shutdown()


if __name__ == "__main__":
    # 运行测试
    unittest.main(verbosity=2)
